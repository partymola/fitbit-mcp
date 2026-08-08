# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.1] - 2026-08-08

### Fixed

- `doctor` no longer reports a database it merely could not open as a corrupt one. A database locked by a sync running at that moment, left mid-recovery by one that crashed, or simply not readable by this user all took the corruption branch, whose remedy is to delete the cache and re-sync. Being unable to read a file says nothing about its contents, and a diagnostic should never advise destroying data on that basis. An unreadable file is now caught before the open, and a failure to open is reported separately from a file that is not a database.
- The database writability check tested the file but not the directory it sits in. SQLite writes its rollback journal beside the database, so a writable file in a read-only directory failed every sync while `doctor` reported no problem - the exact state the finding describes.
- Cache age is measured in whole days between dates rather than from the current time, so the same cache no longer reads stale late in the evening and fresh after midnight. A stored date that is not a calendar date now warns instead of reading as current; dates are kept as the API returned them, and a malformed one sorts above every real date.
- An offline, cache-only host is no longer told to run `fitbit-mcp sync`, which the CLI refuses in that mode. It is pointed at the host that owns the database instead.
- A path pointing at a named pipe made the command hang forever instead of reporting.
- macOS and Windows are no longer reported as headless. Neither sets `DISPLAY` or `WAYLAND_DISPLAY`, and a browser opens there regardless, so every macOS user was told to authorise over an SSH tunnel.
- An environment variable set to an empty value is described as such rather than as the default. It is still an override, and resolves relative to the working directory.

## [0.5.0] - 2026-08-08

### Added

- `fitbit-mcp doctor` checks a setup and reports what needs fixing. It resolves and prints the config and database paths actually in use and where each came from, validates the credential files by shape, and reads the database read-only for schema drift, corruption and how current the cache is. It also reports sync failures recorded in the log: auto-sync suppresses its errors so that queries still serve the cache, which means a dead token otherwise produces no visible symptom beyond data quietly stopping.

  The command is offline and makes no API call, so it costs no rate-limit quota and cannot disturb a token that another host is using. It never creates or modifies anything - notably it will not create the database, so a wrong `FITBIT_MCP_DB_PATH` still reports as missing rather than being silently created empty. No credential value appears in the output. Exit status is non-zero when something needs fixing.

### Packaging

- The container image is built on Python 3.14 instead of 3.13, and 3.14 joins the supported-version classifiers. `requires-python` is unchanged at `>=3.13`: the package still supports both, and only the published image moves. Installing from PyPI is unaffected - that uses whichever Python the user already has.
- Dependency updates are automated. Every dependency, the base image and the CI actions are pinned to exact versions, so nothing changes without a deliberate bump; Dependabot now proposes those bumps rather than leaving the pins to rot.

## [0.4.0] - 2026-08-03

### Changed

- Ported to the `mcp` 2.x server API. 2.0.0 renamed `mcp.server.fastmcp` to `mcp.server.mcpserver` and the `FastMCP` class to `MCPServer`, with no compatibility alias. The tool contract is unchanged: every tool keeps its name, description, and input and output schemas.
- Every dependency is pinned to an exact version instead of a lower bound: `mcp` 2.0.0 and `anyio` 4.14.2, and for development `pytest` 9.1.1, `pytest-asyncio` 1.4.0 and `ruff` 0.16.1.

### Fixed

- A fresh install no longer breaks on import. The `mcp` spec was `>=1.6.0` with no upper bound, so once 2.0.0 was published the resolver picked it and the server failed to start.

### Packaging

- The build toolchain is pinned alongside the dependencies: `setuptools` to an exact version, the `python:3.13-slim` base image by digest, and every GitHub Action to a full commit SHA rather than a moving major tag. A floating tag can change what a build produces with nobody deciding, which is the same failure the dependency pins address.

## [0.3.1] - 2026-07-11

### Packaging

- Listed in the official MCP registry (`io.github.partymola/fitbit-mcp`); the release workflow now publishes to the registry alongside PyPI.

## [0.3.0] - 2026-07-11

### Packaging

- Published to PyPI (`pip install fitbit-mcp` / `uvx fitbit-mcp`) via GitHub Actions Trusted Publishing.

### Added

- `fitbit_get_core_temperature` - retrieves manually-logged core (body) temperature readings (e.g. a forehead/thermometer reading saved to Fitbit via "Save to Fitbit"), distinct from the device-derived nightly skin-temperature variation returned by `fitbit_get_skin_temperature`. Backed by the Fitbit `temp/core` endpoint and covered by the existing `temperature` OAuth scope (no re-auth needed). Because these are entered by hand, a single day can hold several readings - even sharing one (second-resolution) timestamp - so the `core_temperature` cache table is keyed by `(datetime, temp_celsius)`, preserving distinct same-second readings while de-duplicating exact repeats. `fitbit_sync` and `fitbit_trends` (including period comparison) now cover `core_temperature`; its trend leads with the per-period peak and a count of readings >= 38 C, since hand-logged temperatures are sampled mostly during illness and a plain average would mislead.
- `--since YYYY-MM-DD` on `fitbit-mcp sync` (and a `since` argument on the `fitbit_sync` tool) backfills from a given date, overriding the incremental resume-from-last-sync cursor and `--days`. Use it to pull history older than what is already cached.
- `--until YYYY-MM-DD` on `fitbit-mcp sync` (and an `until` argument on the `fitbit_sync` tool) bounds a `--since` backfill, so `--since 2026-03-05 --until 2026-03-09` re-fetches and upserts exactly that window. Use it to repair a gap in the middle of the cache without re-pulling everything from the gap to today. A range backfill never moves the incremental sync cursor backwards.

### Changed

- **Breaking:** the skin-temperature query tool is renamed `fitbit_get_temperature` -> `fitbit_get_skin_temperature`, to disambiguate it from the new `fitbit_get_core_temperature` (relative skin variation vs absolute body temperature). Update any saved prompts or automation that reference the old name. The underlying `skin_temperature` data type, table, and cache are unchanged.

## [0.2.0] - 2026-06-09

### Added

- Offline / cache-only mode via the `FITBIT_MCP_OFFLINE` environment variable. When truthy (`1`, `true`, `yes`, `on`), the server needs no credentials and makes no live API calls: it serves the local SQLite cache only, auto-sync is disabled, and `live=True`, the live-only tools, and `fitbit_sync` return a clear "offline mode" message. Successful responses are tagged with `"offline_mode": true`. Intended for multi-host setups (one host syncs a shared database, others read), CI, and privacy. Default behaviour is unchanged when the variable is unset.
- `fitbit-mcp --version` (and the `-V` short alias) prints the installed package version.
- Continuous integration now runs the test suite on Python 3.14 in addition to 3.13.
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

- Fragmented nights are no longer collapsed to a single session. Fitbit returns one record per sleep session, so a split night (a main sleep plus a nap, or a wake-and-resume logged as two records) used to share a `dateOfSleep` and - because the `sleep` cache is keyed by date - the last record written silently overwrote the rest, leaving a misleadingly short night. Same-night sessions are now aggregated into one row: minutes and stage breakdowns are summed, start/end span the whole night, efficiency is a time-in-bed-weighted mean, and a new `sessions` column records how many records were merged (1 for a normal night). This matches Fitbit's own per-day `summary.totalMinutesAsleep`. Applies to both cached sync and `live=True`. The schema migrates automatically (additive `ALTER TABLE`, idempotent); existing rows keep `sessions = NULL` until the next sync re-fetches that date.
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

[Unreleased]: https://github.com/partymola/fitbit-mcp/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/partymola/fitbit-mcp/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/partymola/fitbit-mcp/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/partymola/fitbit-mcp/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/partymola/fitbit-mcp/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/partymola/fitbit-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/partymola/fitbit-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/partymola/fitbit-mcp/releases/tag/v0.1.0
