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
- **Error messages and logs**: status codes and operation names only - never measurement values or API response bodies. Filesystem paths are governed separately, under Auto-sync behaviour: a CLI subcommand may print one, shared code may not
- **`config/` and `*.db` are gitignored for a reason** - never override this

The `scripts/check-no-data.sh` pre-commit hook rejects database files, config secrets, and large files automatically. Install it per [CONTRIBUTING.md](CONTRIBUTING.md).

## Architecture

- **Entry point**: `src/fitbit_mcp/cli.py` - routes `auth`/`sync`/`import`/`doctor` subcommands or starts the MCP stdio server. `sync` takes `--since`/`--until` to backfill or re-fetch a date range; `import` (backed by `importer.py`) bulk-loads exported data
- **MCP server**: `mcp_instance.py` creates the shared `MCPServer("fitbit-mcp")` instance
- **Auth**: `auth.py` - PKCE OAuth setup and token refresh (8-hour access tokens, 90-day refresh tokens). Scopes are `FITBIT_SCOPES` in `config.py`; after widening them, re-run `fitbit-mcp auth`
- **API**: `api.py` - GET wrapper with auto-refresh and typed exceptions. Reads and parses in separate steps: a body that will not decode or is not JSON raises `ValueError`, which no transport handler catches, so combining them let an intermediary's HTML page escape `run_sync` with no `sync_log` row.
- **Failure classification**: `refresh_token` is a boundary over `_refresh_token` and raises exactly two types. `TokenRefused` only where the server or the credential files judged the credentials unusable; `RefreshNetworkError` for everything else, via a catch-all, so an unanticipated failure lands there by construction rather than by listing exception types. `api.get` maps the first to `FitbitAuthError`, which `doctor` grades FAIL and answers with "run auth" - rotating the token file the syncing host owns - and the second to `FitbitAPIError`, which grades WARN. (In offline mode `doctor` grades both WARN: a token cannot be checked without the network.) **Never widen `TokenRefused` to a condition that can clear on its own** (a rate limit, a 403 from a WAF, an unreadable response). Pinned by `TestTheRefreshBoundary` and `TestAgainstRealTransportFailures` in `tests/test_api.py`. Note: only the two per-day-loop syncs (`_sync_activity`, `_sync_food_log`) sleep-and-retry on 429; range-endpoint types surface a `rate_limited` status and resume on the next sync
- **DB**: `db.py` - SQLite schema (one table per cached data type + `sync_log`), save/query helpers
- **Write path**: every `save_*` goes through `_upsert`, which names only the columns the caller supplied - a named column is updated, an unnamed one keeps its stored value. **Omitting a column and passing it as `None` are different instructions**: the second writes NULL, and is the only way to withdraw a value a provider has retracted, so never collapse the two with `COALESCE(excluded.col, col)`. Column names are interpolated into the statement, so one the table does not have is refused rather than written, as is a row that does not identify itself by its conflict key. `core_temperature` is not upserted - keyed by (datetime, temp_celsius), a changed reading is a new row rather than a correction, so it keeps `INSERT OR IGNORE` - and `sync_log` is append-only. A refused row raises, which on the sync path lands in `run_sync`'s catch-all and abandons the rest of that data type - loud, and a change from the old binding, which ignored a key the table did not have. Pinned by `TestAWriterKeepsWhatItDoesNotName` in `tests/test_db.py`. Every writer in this repo names every column of its table bar one - `importer`'s sleep omits `sessions`, and that omission is the only place the distinction currently changes what is stored
- **Tools**: `tools/` - domain-grouped modules; `sync_tools.py` also exports `auto_sync_if_stale(data_type)`
- **Helpers**: `helpers.py` - `require_auth` (auth-gate decorator on every tool), plus `format_response`/`parse_date`
- **Config**: `config.py` - paths overridable via `FITBIT_MCP_CONFIG_DIR` and `FITBIT_MCP_DB_PATH`; `FITBIT_MCP_OFFLINE` for cache-only mode
- **Doctor**: `doctor.py` - the `doctor` subcommand. Every check is offline and read-only, and two properties are load-bearing rather than incidental: it never opens the database through `db.get_db()` (which would create it and destroy the evidence for the wrong-path and stale-cache checks), and it imports only `config` and `db` - never `auth` or `api`, so no code path can rotate a refresh token that another host owns. Keep both true when adding a check

## Auto-sync behaviour

`get_*` and `fitbit_trends` call `auto_sync_if_stale(data_type)` before querying: it triggers an incremental sync if the last successful sync for that data type was before today (checked via `sync_log`), at most once per data type per day. Failures are swallowed silently - the cache query proceeds regardless.

That silence is why `run_sync` ends its per-type loop with a catch-all writing an `error` row: `sync_log` is the only record any failure leaves, and anything escaping the named handlers escapes into that bare `except`, leaving `doctor` reporting a clean log while the cache ages. **Keep the catch-all, and keep the row's notes to the exception type** - these paths carry API responses, and a message built from one could hold anything. The row is best-effort: writing it is itself a database write, and on a read-only database it fails too, so it is wrapped and the connection is closed in a `finally` around the whole loop rather than per handler. Pinned by `test_an_unnamed_failure_still_leaves_a_sync_log_row`, `test_the_unnamed_failure_message_carries_no_response_content` (both assert the note by equality - a substring check passes with the exception interpolated) and `test_a_database_that_cannot_record_the_failure_does_not_escape`, in `tests/test_sync.py`.

**Nothing built from an API response or an exception's own text reaches a user, a log or `sync_log`.** `run_sync` writes `str(e)` straight into `sync_log.notes` and returns it to the client, so every exception `api.get` raises carries fixed text plus at most a status code and a request path. Not the response body - a Fitbit error body can quote the measurement that caused it - and not the underlying exception, whose text for a TLS or socket failure is an absolute path. The same rule governs `auth.py`'s callback page and `auto_sync_if_stale`'s debug line, which report `type(e).__name__` for that reason - do not restore `exc_info=True` there. Pinned by `test_an_error_body_never_reaches_the_message` and `test_a_network_failure_carries_no_path` in `tests/test_api.py`, by `test_auto_sync_logs_a_type_rather_than_a_traceback` in `tests/test_sync.py`, and for `setup_auth` by the two source-reading assertions in `TestTheCallbackPage`: the exception may travel only as `type(e).__name__`, and the live exception may not be reached without binding it at all (`traceback.format_exc`, `sys.exc_info`, `locals`, a bare `except:`).

**Filesystem paths are a narrower rule than the one above, because two subcommands print them deliberately.** `doctor` exists to report which paths it resolved, and `import` names the directory it was given and the database it wrote to. Both are commands a person typed, and their output - stdout or stderr - is that person's terminal.

Everything else must not carry one, and that includes every `logger.*` call. Logging is shared by both modes: run with no subcommand, the process speaks JSON-RPC on stdout and its log lines go to stderr, where the MCP client collects them, so a log line is closer to a tool response than to a terminal. The test for a new path is therefore **which code prints it, not which stream**: a CLI subcommand may, shared code may not. `sync_log.notes` and every tool response may not either, because both are stored or handed to the model. That is why `importer` prints the directory it was given and logs only a file's name.

Three ordering rules in `run_sync` are load-bearing and easy to undo. `FitbitOfflineError` must keep a clause of its own before the trailing catch-all, or offline mode turns into per-type error rows instead of one clean message; it no longer closes the connection, because the `finally` does. A failure is logged `auth_error` rather than `error` because `doctor` grades the two differently and a dead token is the one that will not clear itself. And the rate-limit wait is bounded by `api.MAX_RATE_LIMIT_WAIT`: the sleep happens on the thread serving an MCP tool call, so an unbounded header hangs it. Pinned by `test_offline_error_propagates_and_closes` and the `TestTheRateLimitWait` cases.

## Seams the suite does not cross

A claim sits at a seam when **no input to the program can make its test fail**. Behavioural tests answer "given this input, what happens"; these are about structure, packaging, or which surface an output lands on. Every leak and every false invariant found in this repo has been at one of them, so check these by execution when they change.

Crossed, and by what:

- **Closures that cannot be imported.** `CallbackHandler` lives inside `setup_auth`, so the only way to check it is to read the source. `TestTheCallbackPage` does, pinning three properties across its five tests: the page escapes what it shows, every `wfile` write goes through `_callback_page`, and the exception reaches the user only as `type(e).__name__` and is never reached unbound.
- **The module import graph.** No behavioural test can see an unused import, and `doctor` importing `auth` or `api` would let a diagnostic rotate a token another host owns. `TestDoctorStaysOffline`.
- **Which code may print a path.** `test_no_logger_call_in_shared_code_carries_a_path` in `tests/test_seams.py`. Key on the logging *method*, not on the receiver's name - `logging.getLogger(__name__).info` is the same call as `logger.info` and a name match misses it.
- **Packaging consistency.** `test_the_declared_version_and_the_lockfile_agree`, same file.
- **The lists a schema change has to move together.** A column added to `SCHEMA` reaches an existing database only if `_migrate` alters the table and `doctor._SELF_HEALING_COLUMNS` excuses the gap meanwhile; miss either and `doctor` grades the database FAIL and tells a user with years of history to re-create it, for something an `ALTER` would have fixed. Adding a column with no migration passed the whole suite, as did deleting one of the two real migrations. `TestTheMigrationLockstep` in `tests/test_seams.py` opens each file in `tests/schema_baselines/`, asserts the result matches `SCHEMA` exactly, and asserts `_SELF_HEALING_COLUMNS` is precisely what `_migrate` added.
  - **Each baseline is `SCHEMA` as a past release shipped it, named for that commit, and must never be edited in place** - refreshed to the current one, the test compares the schema with itself. **Add the outgoing schema whenever `SCHEMA` changes**; delete one only to drop support for databases that old.
  - **One baseline is not enough, and the gap is invisible.** A table the baseline predates is created whole by `CREATE TABLE IF NOT EXISTS`, so a column added to *that* table satisfies a single-baseline check while still breaking the database of a user who has the table and not the column - and the same check then rejects the correct migration, pointing a maintainer at exactly the wrong repair. Covering every released vintage is what makes a green run mean what it says.
- **Two more lists that restate `SCHEMA`'s tables.** A table absent from `_UPSERT_KEYS` raises inside `_upsert`, which on the sync path `run_sync`'s catch-all records as an exception type, leaving `doctor` reporting a clean log; one absent from `_DATA_TABLE_MAP` is quieter still, re-fetching its whole window every run with nothing looking wrong. `test_every_table_is_accounted_for_by_the_lists_that_enumerate_them` names the excluded tables rather than inferring them.
- **That every `save_*` actually writes through `_upsert`.** Only five of the twelve upserted tables have a preservation test, so a helper reverted to its own `INSERT OR REPLACE` keeps its `_UPSERT_KEYS` entry and passes the whole suite while the entry means nothing. `test_every_save_helper_writes_through_the_upsert` reads the source and pins both directions, `save_core_temperature` being the one helper that must not upsert.

Crossed only from outside this repo, which an outside contributor will not have:

- **The mock boundary.** Tool tests patch `api.get`, so the mock sits above the real client and a change to what it accepts or returns is invisible to most of the suite. Partially crossed by the two tests that drive `devices` and `spo2` through the real client - the pattern to copy when a change touches that layer.
- **The wire contract.** The suite calls tool functions directly and never the server, so a tool's description and its input schema are untested: replacing a docstring with nonsense, or changing a parameter's type annotation, passes the whole suite. A rename is caught, but only incidentally - `tests/test_tools.py` imports the functions by name - so do not read that as contract coverage. Dump the tool list and schemas from a real server and diff them across the change.
- **The pre-commit guard.** `scripts/check-no-data.sh` is not exercised by pytest at all. Stage a probe file per class and check reject against expectation.

## Database schema

SQLite at `~/.local/share/fitbit-mcp/fitbit.db` (gitignored). The exact column definitions live in `SCHEMA` in `src/fitbit_mcp/db.py` (the source of truth); the list below is a navigational overview that also notes the non-obvious semantics.

- `heart_rate` - date, resting_hr, zones (JSON)
- `activity` - date, steps, calories_out, active_minutes, very/fairly/lightly active, sedentary, floors, distance_km
- `exercises` - log_id, date, name, duration_min, calories, avg_hr, steps, distance_km, start_time, source, log_type
- `sleep` - date, total_minutes, efficiency, start/end_time, deep/light/rem/wake_minutes, sessions (one row per night; a fragmented night's sessions are summed, `sessions` > 1 flags the split), sleep_period_minutes
- `weight` - date, weight_kg, bmi, fat_pct
- `spo2` - date, avg, min, max, avg_ci_low, avg_ci_high
- `hrv` - date, daily_rmssd, deep_rmssd
- `azm` - date, total_minutes, fat_burn_minutes, cardio_minutes, peak_minutes
- `breathing_rate` - date, breaths_per_min
- `skin_temperature` - date, nightly_relative (degrees C from baseline), log_type, nightly_absolute, baseline
- `core_temperature` - datetime (YYYY-MM-DDThh:mm:ss), date, temp_celsius; PRIMARY KEY (datetime, temp_celsius) - manually-logged body temp keyed by timestamp+value so multiple (even same-second) readings per day are preserved while exact repeats de-dup. **Its `provider` is currently unwritable and stays NULL**: `save_core_temperature` is `INSERT OR IGNORE` over three named columns and the table is deliberately outside `_UPSERT_KEYS`, so a writer that wants to set it must name it. The seam test skips this helper by name and will not notice
- `cardio_fitness` - date, vo2_max_low, vo2_max_high (Fitbit reports as a range), vo2_max
- `food_log` - date, calories_in, water_ml
- `sync_log` - sync history (used by auto-sync to decide when to re-fetch)

**`provider` is on every table above except `sync_log`**, whose `data_type` and timestamp already carry that. It names **the provider of the most recent write, not of the row** - an upsert keeps columns the new writer did not name, so a row can hold one provider's efficiency beside another's stage minutes and `provider` says only who wrote last. NULL means no writer has set it, which in practice is the 0.x era. Any writer that is not the original Fitbit one must name it on every write, or a row it corrects keeps the previous provider's name.

**Four columns exist because the same quantity is defined differently by different providers, and merging them would corrupt a series rather than break it.** Never widen one to hold both.

- `spo2.avg_ci_low`/`avg_ci_high` are a **confidence interval on the average** (`lowerBoundPercentage`/`upperBoundPercentage`), not observed extremes. `min`/`max` are the observed nightly extremes. Averaging the two definitions in one trend reports a step change that reads as physiological.
- `cardio_fitness.vo2_max` is a **single value**; `vo2_max_low`/`vo2_max_high` are a reported range. Writing one value into both ends collapses a real band to a point.
- `skin_temperature.nightly_absolute` and `baseline` are absolute degrees C. `nightly_relative` is their difference, which is what the Fitbit era stored, so the series continues by subtraction rather than restarting.
- `sleep.sleep_period_minutes` is **not** Fitbit's time-in-bed. It is `minutesInSleepPeriod`, the delta between bedtime and wake time. It makes a *stated* efficiency computable; do not use it to reconstruct `efficiency`, which has no source outside the Fitbit era and stays NULL rather than being approximated.

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
