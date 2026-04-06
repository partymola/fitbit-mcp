# fitbit-mcp

MCP server for the Fitbit Web API with OAuth PKCE, local SQLite cache, and trend analysis.

Designed for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and other [MCP](https://modelcontextprotocol.io/) clients. Syncs your Fitbit data to a local database for fast, offline queries - no API calls needed after the initial sync.

## Features

- **OAuth 2.0 PKCE** - Secure auth flow, no client secret needed
- **Local SQLite cache** - Sync once, query instantly
- **Incremental sync** - Only fetches new data since last sync
- **9 MCP tools** - Sync, query (7 data types), and trend analysis
- **Live mode** - Bypass cache and query the API directly
- **CLI** - Auth setup, sync, and JSON import from the command line
- **Rate limit handling** - Automatic retry on 429 responses

## Data types

| Tool | Data |
|------|------|
| `fitbit_get_heart_rate` | Resting HR, HR zones |
| `fitbit_get_activity` | Steps, calories, active minutes, distance |
| `fitbit_get_exercises` | Exercise sessions (name, duration, HR, calories) |
| `fitbit_get_sleep` | Duration, efficiency, sleep stages |
| `fitbit_get_weight` | Weight, BMI, body fat % |
| `fitbit_get_spo2` | Blood oxygen saturation (avg/min/max) |
| `fitbit_get_hrv` | Heart rate variability (RMSSD) |
| `fitbit_trends` | Aggregated averages (weekly/monthly/quarterly) |

## Requirements

- Python 3.13+
- A [Fitbit developer account](https://dev.fitbit.com/apps) with a registered personal app

## Setup

### 1. Install

```bash
pip install .
```

Or for development:

```bash
pip install -e ".[dev]"
```

### 2. Register a Fitbit app

1. Go to [dev.fitbit.com/apps](https://dev.fitbit.com/apps) and create a new app
2. Set **OAuth 2.0 Application Type** to **Personal**
3. Set **Redirect URL** to `http://localhost:8080`
4. Note your **Client ID** (you won't need the client secret - PKCE doesn't use one)

### 3. Authenticate

```bash
fitbit-mcp auth
```

This opens your browser for Fitbit login, exchanges the auth code via PKCE, and saves tokens locally.

Tokens are stored in `~/.config/fitbit-mcp/fitbit_tokens.json` with 0600 permissions. Access tokens expire in 8 hours and are refreshed automatically. Refresh tokens expire after 90 days of inactivity.

### 4. Register with Claude Code

```bash
claude mcp add -s user fitbit -- fitbit-mcp
```

### 5. First sync

Once registered, ask Claude to run `fitbit_sync` or use the CLI:

```bash
fitbit-mcp sync --days 30
```

## CLI usage

```
fitbit-mcp              Start the MCP server (stdio transport)
fitbit-mcp auth         Interactive OAuth setup
fitbit-mcp sync         Sync data to local cache
  --days N              Days of history for first sync (default: 30)
  --types TYPE,...      Data types to sync (default: all)
fitbit-mcp import       Import existing JSON data files
  --data-dir PATH       Directory containing JSON files
```

## MCP tool reference

All query tools accept these common parameters:

- `start_date` - Start date as `YYYY-MM-DD`, `YYYY-MM`, or `30d` (relative). Default: last 30 days.
- `end_date` - End date as `YYYY-MM-DD`. Default: today.
- `live` - If true, fetch from Fitbit API instead of cache.

`fitbit_get_exercises` also accepts:

- `exercise_type` - Filter by activity name (case-insensitive substring match), e.g. `"cycling"`, `"walk"`, `"run"`. Default: all types.

### fitbit_sync

Syncs data from the Fitbit API to the local SQLite cache. Run this before using query tools.

- `data_types` - What to sync: `all`, `heart_rate`, `activity`, `exercises`, `sleep`, `weight`, `spo2`, `hrv`. Comma-separated. Default: `all`.
- `days` - Days of history for first sync (default: 30). Subsequent syncs are incremental.

### fitbit_trends

Aggregated trend analysis from cached data.

- `data_type` - What to analyse: `heart_rate`, `activity`, `exercises`, `sleep`, `weight`, `spo2`, `hrv`. Default: `activity`.
- `period` - Aggregation: `weekly`, `monthly`, `quarterly`. Default: `monthly`.
- `start_date` - Start date. Default: last 12 months (365 days).
- `end_date` - End date. Default: today.
- `compare` - Compare two periods: `last_30d vs previous_30d`, `2026-03 vs 2026-02`, `2026-Q1 vs 2025-Q4`. When set, `period`/`start_date`/`end_date` are ignored.

## OAuth scopes

The following Fitbit API scopes are requested during setup:

| Scope | Data accessed |
|-------|--------------|
| `activity` | Steps, calories, active minutes, distance |
| `heartrate` | Resting HR and HR zones |
| `sleep` | Sleep duration and stages |
| `weight` | Weight, BMI, body fat % |
| `oxygen_saturation` | SpO2 (blood oxygen) |
| `profile` | User profile (user ID, display name) |

These are the minimum scopes needed for all 9 tools. If you only need a subset, you can edit `FITBIT_SCOPES` in `config.py` before setup.

## Configuration

Paths are overridable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `FITBIT_MCP_CONFIG_DIR` | `~/.config/fitbit-mcp/` | Directory for OAuth credentials |
| `FITBIT_MCP_DB_PATH` | `~/.local/share/fitbit-mcp/fitbit.db` | SQLite database path |

## Rate limits

The Fitbit API allows 150 requests per hour. The sync tool handles rate limits automatically, but be aware:

- Activity sync uses 1 API call per day (no date-range endpoint available)
- A 30-day initial sync uses ~30 of your 150/hour quota
- Heart rate, sleep, weight, SpO2, and HRV use date-range endpoints and are much more efficient

Use `live=False` (the default) to query from cache and avoid API calls entirely.

## Data safety

This project includes a pre-commit hook (`scripts/check-no-data.sh`) that prevents accidentally committing:

- Database files (`*.db`, `*.db-journal`, `*.db-wal`)
- Config/credentials (`config/*.json`)
- Large files (>100KB)

Install it after cloning:

```bash
cp scripts/check-no-data.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

## Importing existing data

If you have existing Fitbit data as JSON files (e.g. from a previous export or script), you can bulk-import them:

```bash
fitbit-mcp import --data-dir /path/to/json/files/
```

Expected file names: `heart_rate.json`, `activity.json`, `exercises.json`, `sleep.json`, `weight.json`, `spo2.json`, `hrv.json`. See `src/fitbit_mcp/importer.py` for the expected JSON format.

## License

[GPL-3.0-or-later](LICENSE)
