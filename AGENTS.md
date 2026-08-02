# fitbit-mcp - agent guide

`CLAUDE.md` symlinks to this file. It orients AI agents and contributors working *in* the code, and deliberately does not repeat the user-facing docs:

- **What it is, install, auth, tools, config, CLI, usage** -> [README.md](README.md)
- **Dev environment, running tests, pre-commit hook, PR & security process** -> [CONTRIBUTING.md](CONTRIBUTING.md)

**This is a public open-source repository and health data is sensitive PII.** Read the Data Safety Rules before committing.

## Data Safety Rules

Before committing ANY change, verify:

- **No real health measurements** in code, tests, commits, or docs - no real heart rates, sleep data, step counts, weight, SpO2, or HRV values
- **No personal identifiers** - no real names, Fitbit user IDs, or dates of birth
- **No credentials** - no OAuth tokens, client IDs, API keys, or token files
- **Test fixtures must use fictional data** - obviously fake values and fixed past dates (e.g. 2026-03-10)
- **Error messages and logs**: status codes and operation names only - never measurement values or API response bodies
- **`config/` and `*.db` are gitignored for a reason** - never override this

The `scripts/check-no-data.sh` pre-commit hook rejects database files, config secrets, and large files automatically. Install it per [CONTRIBUTING.md](CONTRIBUTING.md).

## Architecture

- **Entry point**: `src/fitbit_mcp/cli.py` - routes `auth`/`sync`/`import` subcommands or starts the MCP stdio server. `sync` takes `--since`/`--until` to backfill or re-fetch a date range; `import` (backed by `importer.py`) bulk-loads exported data
- **MCP server**: `mcp_instance.py` creates the shared `MCPServer("fitbit-mcp")` instance
- **Auth**: `auth.py` - PKCE OAuth setup and token refresh (8-hour access tokens, 90-day refresh tokens). Scopes are `FITBIT_SCOPES` in `config.py`; after widening them, re-run `fitbit-mcp auth`
- **API**: `api.py` - GET wrapper with auto-refresh and typed exceptions. Note: only the two per-day-loop syncs (`_sync_activity`, `_sync_food_log`) sleep-and-retry on 429; range-endpoint types surface a `rate_limited` status and resume on the next sync
- **DB**: `db.py` - SQLite schema (one table per cached data type + `sync_log`), save/query helpers
- **Tools**: `tools/` - domain-grouped modules; `sync_tools.py` also exports `auto_sync_if_stale(data_type)`
- **Helpers**: `helpers.py` - `require_auth` (auth-gate decorator on every tool), plus `format_response`/`parse_date`
- **Config**: `config.py` - paths overridable via `FITBIT_MCP_CONFIG_DIR` and `FITBIT_MCP_DB_PATH`; `FITBIT_MCP_OFFLINE` for cache-only mode

## Auto-sync behaviour

`get_*` and `fitbit_trends` call `auto_sync_if_stale(data_type)` before querying: it triggers an incremental sync if the last successful sync for that data type was before today (checked via `sync_log`), at most once per data type per day. Failures are swallowed silently - the cache query proceeds regardless.

## Database schema

SQLite at `~/.local/share/fitbit-mcp/fitbit.db` (gitignored). The exact column definitions live in `SCHEMA` in `src/fitbit_mcp/db.py` (the source of truth); the list below is a navigational overview that also notes the non-obvious semantics.

- `heart_rate` - date, resting_hr, zones (JSON)
- `activity` - date, steps, calories_out, active_minutes, very/fairly/lightly active, sedentary, floors, distance_km
- `exercises` - log_id, date, name, duration_min, calories, avg_hr, steps, distance_km, start_time, source, log_type
- `sleep` - date, total_minutes, efficiency, start/end_time, deep/light/rem/wake_minutes, sessions (one row per night; a fragmented night's sessions are summed, `sessions` > 1 flags the split)
- `weight` - date, weight_kg, bmi, fat_pct
- `spo2` - date, avg, min, max
- `hrv` - date, daily_rmssd, deep_rmssd
- `azm` - date, total_minutes, fat_burn_minutes, cardio_minutes, peak_minutes
- `breathing_rate` - date, breaths_per_min
- `skin_temperature` - date, nightly_relative (degrees C from baseline), log_type
- `core_temperature` - datetime (YYYY-MM-DDThh:mm:ss), date, temp_celsius; PRIMARY KEY (datetime, temp_celsius) - manually-logged body temp keyed by timestamp+value so multiple (even same-second) readings per day are preserved while exact repeats de-dup
- `cardio_fitness` - date, vo2_max_low, vo2_max_high (Fitbit reports as a range)
- `food_log` - date, calories_in, water_ml
- `sync_log` - sync history (used by auto-sync to decide when to re-fetch)

## Running tests

```bash
.venv/bin/python -m pytest tests/ -v
```

All tests use tmp SQLite and fictional data. Auto-sync is triggered in tests but fails silently (no real credentials). On a developer machine that has live credentials at `~/.config/fitbit-mcp/`, point `FITBIT_MCP_CONFIG_DIR` at an empty directory before running tests so auto-sync skips the network round-trip.
