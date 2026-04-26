# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
