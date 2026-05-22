# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Offline / cache-only mode via the `FITBIT_MCP_OFFLINE` environment variable. When truthy (`1`, `true`, `yes`, `on`), the server needs no credentials and makes no live API calls: it serves the local SQLite cache only, auto-sync is disabled, and `live=True`, the live-only tools, and `fitbit_sync` return a clear "offline mode" message. Successful responses are tagged with `"offline_mode": true`. Intended for multi-host setups (one host syncs a shared database, others read), CI, and privacy. Default behaviour is unchanged when the variable is unset.
- `fitbit-mcp --version` prints the installed package version.
- Eight new data types and corresponding query tools:
  - `fitbit_get_azm` - Active Zone Minutes with per-zone breakdown (fat burn / cardio / peak)
  - `fitbit_get_breathing_rate` - nightly breaths per minute
  - `fitbit_get_temperature` - nightly skin temperature variation
  - `fitbit_get_cardio_fitness` - VO2 Max / Cardio Fitness Score (low and high of Fitbit's reported range)
  - `fitbit_get_food_log` - daily food calories and water intake
  - `fitbit_get_devices` - paired devices, battery level, last sync (live only)
  - `fitbit_get_lifetime_stats` - all-time totals and personal best records (live only)
  - `fitbit_get_goals` - user-set daily/weekly activity goals (live only)
- `fitbit_sync` and `fitbit_trends` extended to cover the five new cached types (`azm`, `breathing_rate`, `skin_temperature`, `cardio_fitness`, `food_log`).
- Six additional OAuth scopes requested at auth time: `respiratory_rate`, `temperature`, `cardio_fitness`, `location`, `nutrition`, `settings`. Existing users must re-run `fitbit-mcp auth` to grant these and unlock the new tools.
- `sync_log` now records each successful sync's end-date (`last_date_attempted`) so sparse-data syncs (e.g. `food_log` when the user does not log every day) advance the cursor forward instead of re-querying every confirmed-empty day. The schema migrates automatically (additive `ALTER TABLE`, idempotent). Existing users with populated DBs will pay the old cost on their first post-upgrade sync (column starts NULL for all historical rows, so the cursor falls back to the data table's `MAX(date)`); subsequent syncs use the new column and skip the empty-day replay.

### Fixed

- Weight values from `fitbit_get_weight` were returned in stones but labelled as `weight_kg`. The API client previously sent `Accept-Language: en_GB`, which causes the Fitbit Web API to return weight in stones (UK convention) while keeping distance in km. The header is now omitted, so all responses are full metric (kg, km). BMI was unaffected.
- **Migration for existing users:** weight rows cached before this release stay in stones-mislabelled-as-kg form, because incremental sync resumes from the most recent stored date and will not re-fetch older rows. To rebuild the weight cache, purge and re-sync:

  ```
  sqlite3 ~/.local/share/fitbit-mcp/fitbit.db \
      "DELETE FROM weight; DELETE FROM sync_log WHERE data_type='weight';"
  fitbit-mcp sync --types weight --days N
  ```

  Pick `N` to cover the history you want back (default 30). Adjust the path if you set `FITBIT_MCP_DB_PATH`. Other data types are unaffected.

## [0.1.0] - 2026-04-26

### Added

- Initial release.
- OAuth 2.0 PKCE authentication against the Fitbit Web API (no client secret needed).
- Local SQLite cache with auto-sync on stale data (one sync per data type per day, opt-out via `live=True`).
- Incremental sync with configurable history window (default 30 days).
- MCP tools: `fitbit_sync`, `fitbit_get_heart_rate`, `fitbit_get_activity`, `fitbit_get_exercises`, `fitbit_get_sleep`, `fitbit_get_weight`, `fitbit_get_spo2`, `fitbit_get_hrv`, `fitbit_trends`.
- Trend analysis with weekly / monthly / quarterly aggregation and period-over-period comparisons.
- CLI subcommands: `auth`, `sync`, `import` (bulk import existing JSON exports).
- Automatic rate-limit retry on 429 responses.
- Pre-commit hook (`scripts/check-no-data.sh`) blocking commit of databases, tokens, and other secrets.

[Unreleased]: https://github.com/partymola/fitbit-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/partymola/fitbit-mcp/releases/tag/v0.1.0
