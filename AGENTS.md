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

- **Entry point**: `src/fitbit_mcp/cli.py` - routes `auth`/`sync`/`import`/`doctor` subcommands or starts the MCP stdio server. `sync` takes `--since`/`--until` to backfill or re-fetch a date range; `import` (backed by `importer.py`) bulk-loads exported data
- **MCP server**: `mcp_instance.py` creates the shared `MCPServer("fitbit-mcp")` instance
- **Auth**: `auth.py` - PKCE OAuth setup and token refresh (8-hour access tokens, 90-day refresh tokens). Scopes are `FITBIT_SCOPES` in `config.py`; after widening them, re-run `fitbit-mcp auth`
- **API**: `api.py` - GET wrapper with auto-refresh and typed exceptions. Reads and parses in separate steps: a body that will not decode or is not JSON raises `ValueError`, which no transport handler catches, so combining them let an intermediary's HTML page escape `run_sync` with no `sync_log` row.
- **Failure classification**: `refresh_token` is a boundary over `_refresh_token` and raises exactly two types. `TokenRefused` only where the server or the credential files judged the credentials unusable; `RefreshNetworkError` for everything else, via a catch-all, so an unanticipated failure lands there by construction rather than by listing exception types. `api.get` maps the first to `FitbitAuthError`, which `doctor` grades FAIL and answers with "run auth" - rotating the token file the syncing host owns - and the second to `FitbitAPIError`, which grades WARN. (In offline mode `doctor` grades both WARN: a token cannot be checked without the network.) **Never widen `TokenRefused` to a condition that can clear on its own** (a rate limit, a 403 from a WAF, an unreadable response). Pinned by `TestTheRefreshBoundary` and `TestAgainstRealTransportFailures` in `tests/test_api.py`. Note: only the two per-day-loop syncs (`_sync_activity`, `_sync_food_log`) sleep-and-retry on 429; range-endpoint types surface a `rate_limited` status and resume on the next sync
- **DB**: `db.py` - SQLite schema (one table per cached data type + `sync_log`), save/query helpers
- **Tools**: `tools/` - domain-grouped modules; `sync_tools.py` also exports `auto_sync_if_stale(data_type)`
- **Helpers**: `helpers.py` - `require_auth` (auth-gate decorator on every tool), plus `format_response`/`parse_date`
- **Config**: `config.py` - paths overridable via `FITBIT_MCP_CONFIG_DIR` and `FITBIT_MCP_DB_PATH`; `FITBIT_MCP_OFFLINE` for cache-only mode
- **Doctor**: `doctor.py` - the `doctor` subcommand. Every check is offline and read-only, and two properties are load-bearing rather than incidental: it never opens the database through `db.get_db()` (which would create it and destroy the evidence for the wrong-path and stale-cache checks), and it imports only `config` and `db` - never `auth` or `api`, so no code path can rotate a refresh token that another host owns. Keep both true when adding a check

## Auto-sync behaviour

`get_*` and `fitbit_trends` call `auto_sync_if_stale(data_type)` before querying: it triggers an incremental sync if the last successful sync for that data type was before today (checked via `sync_log`), at most once per data type per day. Failures are swallowed silently - the cache query proceeds regardless.

That silence is why `run_sync` ends its per-type loop with a catch-all writing an `error` row: `sync_log` is the only record any failure leaves, and anything escaping the named handlers escapes into that bare `except`, leaving `doctor` reporting a clean log while the cache ages. **Keep the catch-all, and keep the row's notes to the exception type** - these paths carry API responses, and a message built from one could hold anything. The row is best-effort: writing it is itself a database write, and on a read-only database it fails too, so it is wrapped and the connection is closed in a `finally` around the whole loop rather than per handler. Pinned by `test_an_unnamed_failure_still_leaves_a_sync_log_row`, `test_the_unnamed_failure_message_carries_no_response_content` (both assert the note by equality - a substring check passes with the exception interpolated) and `test_a_database_that_cannot_record_the_failure_does_not_escape`, in `tests/test_sync.py`.

**No message built from an API response, an exception's own text, or a filesystem path reaches a user, a log or `sync_log`.** `run_sync` writes `str(e)` straight into `sync_log.notes` and returns it to the client, so every exception `api.get` raises carries fixed text plus at most a status code and a request path. Not the response body - a Fitbit error body can quote the measurement that caused it - and not the underlying exception, whose text for a TLS or socket failure is an absolute path. Pinned by `test_an_error_body_never_reaches_the_message` and `test_a_network_failure_carries_no_path` in `tests/test_api.py`.

Three ordering rules in `run_sync` are load-bearing and easy to undo. `FitbitOfflineError` must keep a clause of its own before the trailing catch-all, or offline mode turns into per-type error rows instead of one clean message; it no longer closes the connection, because the `finally` does. A failure is logged `auth_error` rather than `error` because `doctor` grades the two differently and a dead token is the one that will not clear itself. And the rate-limit wait is bounded by `api.MAX_RATE_LIMIT_WAIT`: the sleep happens on the thread serving an MCP tool call, so an unbounded header hangs it. Pinned by `test_offline_error_propagates_and_closes` and the `TestTheRateLimitWait` cases.

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

All tests use tmp SQLite and fictional data. Auto-sync is triggered in tests but fails silently (no real credentials).

On a machine that has live credentials, isolate them by pointing `HOME` at a throwaway directory, so the XDG defaults resolve somewhere empty and auto-sync skips the network round-trip:

```bash
FAKE=$(mktemp -d)
env -u FITBIT_MCP_CONFIG_DIR -u FITBIT_MCP_DB_PATH HOME="$FAKE" .venv/bin/python -m pytest tests/ -q
```

Do not isolate by setting `FITBIT_MCP_CONFIG_DIR` to an empty directory: `test_default_paths_exist` asserts the *default* config directory is named `fitbit-mcp`, and the override makes it the temp directory's name instead, so that test fails for a reason that has nothing to do with the change under test.
