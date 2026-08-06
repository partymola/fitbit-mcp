"""Preflight diagnostic: report what is wrong with a setup, and how to fix it.

Every check here is offline and read-only. Two consequences are load-bearing
rather than incidental:

- Nothing is opened through `db.get_db()`, which creates the database if it
  is absent. Doing so would manufacture an empty DB at the resolved path and
  destroy the evidence for the misconfigured-path and stale-cache checks - the
  two this command exists for. The database is opened read-only throughout.
- No credential value is ever placed in a finding. Output is meant to be
  pasted into a bug report, so files are described by shape - present, parseable,
  which fields are set - and never by content.

Live validation (token introspection, scope diffing) is deliberately absent: it
spends API quota, and on a shared credential file a refresh triggered by a
diagnostic can rotate the token and break the host that legitimately owns it.
"""

import json
import os
import socket
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from . import config, db

OK = "ok"
WARN = "warn"
FAIL = "fail"

_SEVERITY_MARK = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}

# Fitbit refresh tokens expire after 90 days of disuse. A token file untouched
# for longer than that is almost certainly dead, which is worth saying before
# the user discovers it mid-sync.
_REFRESH_TOKEN_LIFETIME = timedelta(days=90)

# Google OAuth client ids carry this suffix; Fitbit's are short alphanumerics.
# Which one is present says which API the credentials were made for, which is
# the first thing to establish once a user is migrating between the two.
_GOOGLE_CLIENT_ID_SUFFIX = ".apps.googleusercontent.com"

# Columns db._migrate() adds to an older database on the next open. Keep in
# step with it: listing one here that it does not add hides a real fault.
_SELF_HEALING_COLUMNS = {("sync_log", "last_date_attempted"), ("sleep", "sessions")}

# A cache older than this has stopped being updated rather than merely lagging.
# Auto-sync refreshes each type at most once a day, so three days without a new
# row is past what a missed run or a day off the wrist explains.
_CACHE_STALE_AFTER = timedelta(days=3)


@dataclass
class Finding:
    name: str
    severity: str
    detail: str
    fix: str | None = None


def _open_db_readonly(path: Path) -> closing:
    """Open the database with no possibility of creating or altering it.

    The path is percent-encoded because this is a URI, not a filename: an
    unescaped `#` would start a fragment, so `?mode=ro` would land inside it
    and be silently ignored - handing back a writable connection to a
    truncated path. `quote` leaves `/` alone and escapes `#` and `?`.

    Encoding via `os.fsencode` rather than passing the str: a filename holding
    non-UTF-8 bytes arrives as surrogate escapes, which `quote` refuses. Going
    through bytes round-trips those unchanged. `Path.as_uri()` is not usable
    at all here - it rejects relative paths, and FITBIT_MCP_DB_PATH may be one.
    """
    conn = sqlite3.connect(f"file:{quote(os.fsencode(path))}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return closing(conn)


def _reference_schema() -> dict[str, set[str]]:
    """Tables and columns this version expects, read from db.SCHEMA itself.

    Built by running the real schema into an in-memory database rather than
    parsing SQL or restating a column list, so it cannot drift from the code.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(db.SCHEMA)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: {r[1] for r in conn.execute(f"PRAGMA table_info('{t}')")} for t in tables}
    finally:
        conn.close()


def _describe_path_source(env_var: str) -> str:
    return f"from ${env_var}" if os.environ.get(env_var) else "default"


def _timestamp_or_none(value) -> datetime | None:
    """Convert an epoch-seconds value, or None if it is not one.

    Out-of-range values raise rather than clamp, and they are not exotic - a
    token written with milliseconds instead of seconds lands tens of thousands
    of years out. A diagnostic must report that, not die on it.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value)
    except (ValueError, OverflowError, OSError):
        return None


def check_environment() -> list[Finding]:
    findings = [
        Finding(
            "config path",
            OK,
            f"{config.CONFIG_DIR} ({_describe_path_source('FITBIT_MCP_CONFIG_DIR')})",
        ),
        Finding(
            "database path",
            OK,
            f"{config.DB_PATH} ({_describe_path_source('FITBIT_MCP_DB_PATH')})",
        ),
    ]

    # Warn only on a value that is neither on nor off - "0" and "false" mean
    # off and are not mistakes, and an empty value is the systemd idiom for
    # blanking a variable. Flagging those would report correct usage as broken.
    raw_offline = (os.environ.get("FITBIT_MCP_OFFLINE") or "").strip().lower()
    recognised = config.OFFLINE_TRUTHY_VALUES + config.OFFLINE_FALSY_VALUES
    if raw_offline and raw_offline not in recognised:
        findings.append(
            Finding(
                "offline mode",
                WARN,
                "FITBIT_MCP_OFFLINE is set to an unrecognised value and so parses "
                "as OFF; this host will try live API calls. Accepted values: "
                f"{', '.join(recognised)}.",
                "Correct the value, or unset it if live access is intended.",
            )
        )
    else:
        findings.append(
            Finding("offline mode", OK, "on (cache only)" if config.OFFLINE_MODE else "off (live)")
        )

    return findings


def _check_config_file() -> list[Finding]:
    path = config.FITBIT_CONFIG_PATH
    if not path.exists():
        return [
            Finding(
                "app config",
                FAIL,
                f"No fitbit_config.json at {path}.",
                "Run `fitbit-mcp auth` to register your app and authorise access. "
                "If you set it up with FITBIT_MCP_CONFIG_DIR set - a systemd unit "
                "does this - export the same value before running this command.",
            )
        ]

    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return [
            Finding(
                "app config",
                FAIL,
                "fitbit_config.json is unreadable or malformed.",
                "Re-run `fitbit-mcp auth`.",
            )
        ]

    client_id = data.get("client_id") if isinstance(data, dict) else None
    if not client_id or not isinstance(client_id, str):
        return [
            Finding(
                "app config",
                FAIL,
                "fitbit_config.json is malformed: no client_id.",
                "Re-run `fitbit-mcp auth` and enter your client ID again.",
            )
        ]

    if client_id.endswith(_GOOGLE_CLIENT_ID_SUFFIX):
        return [
            Finding(
                "app config",
                WARN,
                "client_id is a Google OAuth client. This build targets the Fitbit "
                "Web API, which expects a Fitbit application id.",
                "Use a Fitbit app id, or a build that targets the Google Health API.",
            )
        ]

    return [Finding("app config", OK, "client_id present (Fitbit application)")]


def _check_token_file() -> list[Finding]:
    path = config.FITBIT_TOKENS_PATH
    if not path.exists():
        return [
            Finding(
                "credentials",
                FAIL,
                f"No fitbit_tokens.json at {path}.",
                "Run `fitbit-mcp auth`.",
            )
        ]

    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return [
            Finding(
                "credentials",
                FAIL,
                "fitbit_tokens.json is unreadable or malformed.",
                "Re-run `fitbit-mcp auth`.",
            )
        ]

    if not isinstance(data, dict):
        return [
            Finding(
                "credentials",
                FAIL,
                "fitbit_tokens.json is malformed: expected an object.",
                "Re-run `fitbit-mcp auth`.",
            )
        ]

    findings = []
    missing = [k for k in ("access_token", "refresh_token") if not data.get(k)]
    if missing:
        findings.append(
            Finding(
                "credentials",
                FAIL,
                f"fitbit_tokens.json is missing: {', '.join(missing)}.",
                "Re-run `fitbit-mcp auth`.",
            )
        )
    else:
        findings.append(Finding("credentials", OK, "access and refresh tokens present"))

    expires_at = data.get("expires_at")
    when = _timestamp_or_none(expires_at)
    if when is not None:
        if expires_at < time.time():
            findings.append(
                Finding(
                    "access token",
                    OK,
                    f"expired at {when:%Y-%m-%d %H:%M} - normal between syncs; "
                    "it is refreshed on the next call.",
                )
            )
        else:
            findings.append(Finding("access token", OK, f"valid until {when:%Y-%m-%d %H:%M}"))
    else:
        findings.append(
            Finding(
                "access token",
                WARN,
                "expires_at is missing, not a number, or not a usable timestamp, "
                "so expiry cannot be checked. A value in milliseconds rather than "
                "seconds does this.",
                "Re-run `fitbit-mcp auth`.",
            )
        )

    findings.extend(_check_token_file_writability(path))
    findings.extend(_check_refresh_token_age(path))
    return findings


def _check_token_file_writability(path: Path) -> list[Finding]:
    """An unwritable token file loses the rotated refresh token on next use.

    The refresh call succeeds and Fitbit rotates server-side before the result
    is written, so a failed write leaves no working token anywhere.

    Only the file is checked. auth.py rewrites it in place with O_WRONLY|
    O_TRUNC, which needs no write permission on the directory, so a read-only
    config dir holding a writable token file works and must not be reported.
    """
    if os.access(path, os.W_OK):
        return []
    return [
        Finding(
            "credentials",
            FAIL,
            "fitbit_tokens.json is not writable by this user. Fitbit rotates the "
            "refresh token on every use, so the next refresh will succeed remotely "
            "and then fail to save - leaving no usable token at all.",
            "Fix ownership/permissions before the next sync runs.",
        )
    ]


def _check_refresh_token_age(path: Path) -> list[Finding]:
    try:
        written = _timestamp_or_none(path.stat().st_mtime)
    except OSError:
        return []
    if written is None:
        return []

    age = datetime.now() - written
    if age < _REFRESH_TOKEN_LIFETIME:
        return []
    return [
        Finding(
            "refresh token",
            WARN,
            f"Token file has not been rewritten for {age.days} days; Fitbit "
            "refresh tokens expire after 90 days of disuse.",
            "Run `fitbit-mcp auth` if syncs are failing.",
        )
    ]


def check_credentials() -> list[Finding]:
    if config.OFFLINE_MODE:
        return [Finding("credentials", OK, "not required in offline mode")]
    return _check_config_file() + _check_token_file()


def check_database() -> list[Finding]:
    path = config.DB_PATH
    if not path.exists():
        severity = FAIL if config.OFFLINE_MODE else WARN
        return [
            Finding(
                "database",
                severity,
                f"No database at {path}."
                + (
                    " Offline mode serves the cache only, so there is nothing to read."
                    if config.OFFLINE_MODE
                    else " It is created on the first sync."
                ),
                "Check FITBIT_MCP_DB_PATH points at the database the syncing host writes."
                if config.OFFLINE_MODE
                else "Run `fitbit-mcp sync` to populate it.",
            )
        ]

    if path.is_dir():
        return [Finding("database", FAIL, f"{path} is a directory, not a database file.")]

    findings = []
    # A read-only cache is the documented multi-host arrangement, not a fault:
    # one host syncs and the rest read. Only worth reporting where this host is
    # expected to write.
    if not config.OFFLINE_MODE and not os.access(path, os.W_OK):
        findings.append(
            Finding(
                "database",
                WARN,
                "Database is not writable by this user; queries will work but "
                "every sync will fail.",
                "Fix ownership/permissions, or run syncs as the owning user.",
            )
        )

    try:
        with _open_db_readonly(path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                return findings + [
                    Finding(
                        "database",
                        FAIL,
                        "Database fails its integrity check.",
                        "Restore from backup, or delete it and re-sync.",
                    )
                ]
            findings.extend(_check_schema(conn))
            findings.extend(_check_freshness(conn))
    except sqlite3.DatabaseError:
        return findings + [
            Finding(
                "database",
                FAIL,
                f"{path} is not a readable SQLite database.",
                "Restore from backup, or delete it and re-sync.",
            )
        ]

    return findings


def _check_schema(conn: sqlite3.Connection) -> list[Finding]:
    """Report only schema drift that the next ordinary command will NOT repair.

    A whole missing table is recreated by db.get_db()'s `CREATE TABLE IF NOT
    EXISTS`, and db._migrate() adds the columns in _SELF_HEALING_COLUMNS. None
    of that is a problem for the user, and reporting it would attach the
    remediation below - destroying and rebuilding a cache that needed nothing.
    A column missing anywhere else has no migration and does break its sync.
    """
    expected = _reference_schema()
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    absent, problems = [], []
    for table, columns in sorted(expected.items()):
        if table not in present:
            absent.append(table)
            continue
        actual = {r[1] for r in conn.execute(f"PRAGMA table_info('{table}')")}
        missing = {c for c in columns - actual if (table, c) not in _SELF_HEALING_COLUMNS}
        if missing:
            problems.append(f"{table}.{'/'.join(sorted(missing))}")

    findings = []
    if problems:
        findings.append(
            Finding(
                "schema",
                FAIL,
                f"Database predates this version and has no migration for: "
                f"{', '.join(problems)}. Syncing these types will fail.",
                "Back the database up, then re-create and re-import it.",
            )
        )
    if absent:
        # Recreated empty by get_db()'s CREATE TABLE IF NOT EXISTS, so this is
        # not a fault to remedy - but it is not "matches this version" either,
        # and any history those tables held is gone.
        findings.append(
            Finding(
                "schema",
                WARN,
                f"{len(absent)} table(s) absent: {', '.join(absent)}. They are "
                "recreated empty on the next open, so any history in them is lost.",
                "Re-sync to refill them.",
            )
        )
    if not findings:
        findings.append(Finding("schema", OK, "matches this version"))
    return findings


def _check_freshness(conn: sqlite3.Connection) -> list[Finding]:
    newest = {}
    for data_type in config.CACHED_DATA_TYPES:
        try:
            row = conn.execute(f"SELECT MAX(date) FROM '{data_type}'").fetchone()
        except sqlite3.DatabaseError:
            continue
        if row and row[0]:
            newest[data_type] = row[0]

    if not newest:
        return [
            Finding(
                "cache",
                WARN,
                "Database has no data in any table.",
                "Run `fitbit-mcp sync --days 30`.",
            )
        ]

    latest = max(newest.values())
    summary = f"{len(newest)} data types cached, newest date {latest}"

    # Staleness is judged on the newest row across all types, not per type.
    # Types only written when the user logs something - weight, food - lag by
    # design, and flagging those individually would cry wolf on a healthy cache.
    try:
        age = datetime.now() - datetime.strptime(latest, "%Y-%m-%d")
    except ValueError:
        return [Finding("cache", OK, summary)]

    if age <= _CACHE_STALE_AFTER:
        return [Finding("cache", OK, summary)]
    return [
        Finding(
            "cache",
            WARN,
            f"{summary} - {age.days} days old, so syncing has stopped.",
            "Check the sync log below. In offline mode the cause is on the "
            "syncing host, not this one.",
        )
    ]


def check_sync_health() -> list[Finding]:
    """Read the sync log for failures that never surfaced anywhere else.

    Auto-sync suppresses its exceptions by design so that a read still serves
    the cache; the cost is that a dead token produces no visible error. The
    log is the only in-band record that this is happening.
    """
    path = config.DB_PATH
    if not path.exists():
        return []

    try:
        with _open_db_readonly(path) as conn:
            # The latest attempt per type is what says whether it is broken
            # NOW. Counting failures over a window instead would keep reporting
            # a problem that was fixed weeks ago, until enough rows aged out.
            rows = conn.execute(
                "SELECT data_type, status, notes, synced_at FROM sync_log s "
                "WHERE synced_at = (SELECT MAX(synced_at) FROM sync_log "
                "                   WHERE data_type = s.data_type)"
            ).fetchall()
    except sqlite3.DatabaseError:
        return []

    if not rows:
        return []

    failing = [r for r in rows if r["status"] in ("auth_error", "error")]
    if not failing:
        if any(r["status"] == "partial" and (r["notes"] or "") == "rate limited" for r in rows):
            return [
                Finding(
                    "sync log",
                    WARN,
                    "The last sync was cut short by Fitbit's 150 requests/hour cap.",
                    "It resumes on the next run; use --types to sync fewer types at once.",
                )
            ]
        return [Finding("sync log", OK, "no failures recorded")]

    types = ", ".join(sorted(r["data_type"] for r in failing))
    auth = [r for r in failing if r["status"] == "auth_error"]
    detail = (
        f"Last sync failed for: {types} ({'auth' if auth else 'error'}, "
        f"most recent {max(r['synced_at'] for r in failing)}). Auto-sync "
        "suppresses these, so queries keep serving stale cache silently."
    )

    if config.OFFLINE_MODE:
        # This host does not sync; the log belongs to whichever host does, and
        # both remedies below are refused here (cli.py exits on `sync` offline).
        return [
            Finding(
                "sync log",
                WARN,
                detail + " This host is cache-only, so the fault is on the syncing host.",
                "Fix it there; nothing on this host will change it.",
            )
        ]

    return [
        Finding(
            "sync log",
            FAIL if auth else WARN,
            detail,
            "Run `fitbit-mcp auth` if this is an auth failure, then "
            "`fitbit-mcp sync --since <first missing date>` to backfill.",
        )
    ]


def check_auth_prerequisites() -> list[Finding]:
    """Things that break `fitbit-mcp auth` itself, checked before it is needed."""
    if config.OFFLINE_MODE:
        return []

    findings = []
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("localhost", config.FITBIT_CALLBACK_PORT))
        except OSError:
            findings.append(
                Finding(
                    "auth callback",
                    WARN,
                    f"Port {config.FITBIT_CALLBACK_PORT} is in use, so `fitbit-mcp auth` "
                    "cannot receive the OAuth callback.",
                    "Free the port before authorising; it must match the registered "
                    "redirect URL and so cannot be changed.",
                )
            )

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        findings.append(
            Finding(
                "auth browser",
                WARN,
                "No display detected, so `fitbit-mcp auth` cannot open a browser and "
                "the callback must still reach this host.",
                f"Authorise over a tunnel: ssh -L {config.FITBIT_CALLBACK_PORT}:"
                f"localhost:{config.FITBIT_CALLBACK_PORT} <user>@<host>",
            )
        )

    return findings


def run_checks() -> list[Finding]:
    findings = []
    for check in (
        check_environment,
        check_credentials,
        check_database,
        check_sync_health,
        check_auth_prerequisites,
    ):
        try:
            findings.extend(check())
        except Exception as e:
            # A diagnostic that dies on a broken setup is worthless precisely
            # when it is needed, so no single check may end the run. Only the
            # exception type is reported: these checks read files containing
            # tokens, and a message built from file content could carry one.
            findings.append(
                Finding(
                    check.__name__,
                    FAIL,
                    f"This check could not run ({type(e).__name__}).",
                    "Please report this as a bug.",
                )
            )
    return findings


def format_report(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        lines.append(f"[{_SEVERITY_MARK[f.severity]}] {f.name}: {f.detail}")
        if f.fix and f.severity != OK:
            lines.append(f"         -> {f.fix}")

    failures = sum(1 for f in findings if f.severity == FAIL)
    warnings = sum(1 for f in findings if f.severity == WARN)
    lines.append("")
    if failures:
        lines.append(f"{failures} problem(s) need fixing, {warnings} warning(s).")
    elif warnings:
        lines.append(f"No blocking problems, {warnings} warning(s).")
    else:
        lines.append("All checks passed.")
    return "\n".join(lines)


def run_doctor() -> int:
    findings = run_checks()
    print(format_report(findings))
    return 1 if any(f.severity == FAIL for f in findings) else 0
