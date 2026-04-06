# fitbit-mcp

**This is a public open-source repository.** Health data is sensitive PII. Every commit, PR, and file is visible to anyone.

## Data Safety Rules

Before committing ANY change, verify:

- **No real health measurements** in code, tests, commits, or docs - no real heart rates, sleep data, step counts, weight, SpO2, or HRV values
- **No personal identifiers** - no real names, Fitbit user IDs, or dates of birth
- **No credentials** - no OAuth tokens, client IDs, API keys, or token files
- **Test fixtures must use fictional data** - use obviously fake values and fixed past dates (e.g. 2026-03-10)
- **Error messages and logs**: status codes and operation names only - never measurement values or API response bodies
- **`config/` and `*.db` are gitignored for a reason** - never override this

The pre-commit hook (`scripts/check-no-data.sh`) automatically rejects database files, config secrets, and large files. Install after cloning:

```bash
cp scripts/check-no-data.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

## Quick Reference

```bash
fitbit-mcp auth     # Interactive OAuth setup (opens browser)
fitbit-mcp sync     # Sync data to local cache (optional - tools auto-sync on first use)
fitbit-mcp          # Start MCP server (stdio transport, used by Claude Code)
```

## Tools

| Tool | Source | Purpose |
|------|--------|---------|
| `fitbit_sync` | Live API -> SQLite | Incremental sync (heart_rate, activity, exercises, sleep, weight, spo2, hrv) |
| `fitbit_get_heart_rate` | Cache (auto-sync) / Live | Resting HR, HR zones |
| `fitbit_get_activity` | Cache (auto-sync) / Live | Steps, calories, active minutes, distance |
| `fitbit_get_exercises` | Cache (auto-sync) / Live | Exercise sessions (name, duration, HR, calories) |
| `fitbit_get_sleep` | Cache (auto-sync) / Live | Duration, efficiency, sleep stages |
| `fitbit_get_weight` | Cache (auto-sync) / Live | Weight, BMI, body fat % |
| `fitbit_get_spo2` | Cache (auto-sync) / Live | Blood oxygen saturation (avg/min/max) |
| `fitbit_get_hrv` | Cache (auto-sync) / Live | Heart rate variability (RMSSD) |
| `fitbit_trends` | Cache (auto-sync) | Period averages, comparisons, min/max/delta |

All `get_*` and `fitbit_trends` tools auto-sync on the first query of each day per data type. Use `live=True` to bypass the cache entirely.

## Architecture

- **Entry point**: `src/fitbit_mcp/cli.py` - routes `auth`/`sync`/`import` subcommands or starts MCP stdio server
- **FastMCP**: `mcp_instance.py` creates the shared `FastMCP("fitbit-mcp")` instance
- **Auth**: `auth.py` - PKCE OAuth setup, token refresh (8-hour access tokens, 90-day refresh tokens)
- **API**: `api.py` - GET wrapper with auto-refresh, rate limit retry, typed exceptions
- **DB**: `db.py` - SQLite schema (7 data tables + `sync_log`), save/query helpers
- **Tools**: `tools/` - domain-grouped modules; `sync_tools.py` also exports `auto_sync_if_stale(data_type)`
- **Config**: `config.py` - paths overridable via `FITBIT_MCP_CONFIG_DIR` and `FITBIT_MCP_DB_PATH`

## Auto-sync behaviour

`get_*` and `fitbit_trends` call `auto_sync_if_stale(data_type)` before querying. This triggers an incremental sync if the last successful sync for that data type was before today (checked via `sync_log`). Failures are silently swallowed - the cache query proceeds regardless. At most one auto-sync per data type per day.

## Auth and Credentials

- Personal OAuth app registered at https://dev.fitbit.com/apps
- PKCE flow - no client secret needed
- Redirect URL: `http://localhost:8080`
- Credentials stored in `~/.config/fitbit-mcp/fitbit_config.json` and `fitbit_tokens.json` (gitignored)
- Access tokens expire in 8 hours (auto-refresh). Refresh tokens expire after 90 days of inactivity.

## Database

SQLite at `~/.local/share/fitbit-mcp/fitbit.db` (gitignored). Tables:
- `heart_rate` - date, resting_hr, zones (JSON)
- `activity` - date, steps, calories_out, active_minutes, very/fairly/lightly active, sedentary, floors, distance_km
- `exercises` - log_id, date, name, duration_min, calories, avg_hr, steps, distance_km, start_time, source, log_type
- `sleep` - date, total_minutes, efficiency, start/end_time, deep/light/rem/wake_minutes
- `weight` - date, weight_kg, bmi, fat_pct
- `spo2` - date, avg, min, max
- `hrv` - date, daily_rmssd, deep_rmssd
- `sync_log` - sync history (used by auto-sync to decide when to re-fetch)

## Rate Limits

Fitbit API: 150 requests/hour. Activity sync uses 1 call per day (no range endpoint) - a 30-day initial sync uses ~30 quota. Other data types use range endpoints and are much more efficient. Rate limit errors are auto-retried.

## Running Tests

```bash
cd fitbit-mcp
.venv/bin/python -m pytest tests/ -v   # 187 tests
```

All tests use tmp SQLite and fictional data. Auto-sync is triggered in tests but fails silently (no real credentials).

## Troubleshooting

- **"Fitbit not configured"**: Run `fitbit-mcp auth`
- **"Token refresh failed"**: Re-run `fitbit-mcp auth` (refresh token expired after 90 days inactivity)
- **Empty results**: Auto-sync may have failed - check auth with `fitbit-mcp auth`, then run `fitbit_sync` explicitly
- **Rate limited**: Fitbit quota is 150/hour. Wait for reset, then retry.
- **Python 3.13+ required**
