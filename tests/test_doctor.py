"""Tests for the doctor preflight diagnostic.

The properties pinned here are the ones that make a diagnostic trustworthy:
it must not change the thing it inspects, must not leak credentials into
output a user will paste into a bug report, and must survive every broken
setup it exists to describe.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

from fitbit_mcp import db, doctor

# Sentinels chosen so a leak is unambiguous in any output format.
FAKE_ACCESS_TOKEN = "ACCESS-TOKEN-MUST-NOT-APPEAR-A1B2C3"
FAKE_REFRESH_TOKEN = "REFRESH-TOKEN-MUST-NOT-APPEAR-D4E5F6"
FAKE_CLIENT_SECRET = "CLIENT-SECRET-MUST-NOT-APPEAR-G7H8I9"


@pytest.fixture
def setup_paths(tmp_path, monkeypatch):
    """Point config and DB at a tmp dir without creating anything in it."""
    config_dir = tmp_path / "config"
    db_path = tmp_path / "data" / "fitbit.db"
    monkeypatch.setattr("fitbit_mcp.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("fitbit_mcp.config.FITBIT_CONFIG_PATH", config_dir / "fitbit_config.json")
    monkeypatch.setattr("fitbit_mcp.config.FITBIT_TOKENS_PATH", config_dir / "fitbit_tokens.json")
    monkeypatch.setattr("fitbit_mcp.config.DB_PATH", db_path)
    monkeypatch.setattr("fitbit_mcp.config.OFFLINE_MODE", False)
    return config_dir, db_path


def _write_credentials(config_dir, expires_at=None):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "fitbit_config.json").write_text(
        json.dumps({"client_id": "23ABCD", "client_secret": FAKE_CLIENT_SECRET})
    )
    (config_dir / "fitbit_tokens.json").write_text(
        json.dumps(
            {
                "access_token": FAKE_ACCESS_TOKEN,
                "refresh_token": FAKE_REFRESH_TOKEN,
                "user_id": "ABC123",
                "expires_at": expires_at if expires_at is not None else time.time() + 3600,
            }
        )
    )


class _FakeCursor:
    """Minimal stand-in for a sqlite3 cursor holding one row."""

    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


# --- Invariant 1: doctor never mutates what it inspects ---


def test_does_not_create_the_database(setup_paths):
    """The wrong-path check is only meaningful if doctor cannot manufacture a DB."""
    _config_dir, db_path = setup_paths

    doctor.run_checks()

    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_does_not_create_the_config_directory(setup_paths):
    config_dir, _db_path = setup_paths

    doctor.run_checks()

    assert not config_dir.exists()


def test_does_not_modify_an_existing_database(setup_paths, tmp_path):
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    conn.close()
    before = db_path.read_bytes()

    doctor.run_checks()

    assert db_path.read_bytes() == before


# --- Invariant 2: doctor never prints secret values ---


def test_never_prints_token_or_secret_values(setup_paths, capsys):
    config_dir, _db_path = setup_paths
    _write_credentials(config_dir)

    doctor.run_doctor()

    out = capsys.readouterr()
    combined = out.out + out.err
    assert FAKE_ACCESS_TOKEN not in combined
    assert FAKE_REFRESH_TOKEN not in combined
    assert FAKE_CLIENT_SECRET not in combined


def test_findings_carry_no_secret_values(setup_paths):
    """Belt and braces: the structured findings are what a caller might log."""
    config_dir, _db_path = setup_paths
    _write_credentials(config_dir)

    blob = " ".join(f"{f.name} {f.detail} {f.fix or ''}" for f in doctor.run_checks())

    assert FAKE_ACCESS_TOKEN not in blob
    assert FAKE_REFRESH_TOKEN not in blob
    assert FAKE_CLIENT_SECRET not in blob


# --- Invariant 3: doctor survives every broken setup ---


def test_survives_completely_missing_setup(setup_paths):
    findings = doctor.run_checks()

    assert any(f.severity == doctor.FAIL for f in findings)


def test_survives_unparseable_config_and_token_files(setup_paths):
    config_dir, _db_path = setup_paths
    config_dir.mkdir(parents=True)
    (config_dir / "fitbit_config.json").write_text("{not json")
    # Malformed but secret-bearing: the error path must not echo file content.
    (config_dir / "fitbit_tokens.json").write_text(
        '{"access_token": "' + FAKE_ACCESS_TOKEN + '" NOT JSON'
    )

    findings = doctor.run_checks()

    assert any(
        "unreadable" in f.detail.lower() or "malformed" in f.detail.lower() for f in findings
    )
    assert all(FAKE_ACCESS_TOKEN not in f"{f.detail} {f.fix or ''}" for f in findings)


def test_survives_credential_files_that_are_not_utf8(setup_paths):
    config_dir, _db_path = setup_paths
    config_dir.mkdir(parents=True)
    (config_dir / "fitbit_config.json").write_bytes(b"\xff\xfe not text")
    (config_dir / "fitbit_tokens.json").write_bytes(b"\xff\xfe not text")

    findings = doctor.run_checks()

    assert any(f.severity == doctor.FAIL for f in findings)


def test_survives_an_expires_at_in_milliseconds(setup_paths):
    """Seconds-vs-milliseconds is a routine OAuth slip; it must not crash."""
    config_dir, _db_path = setup_paths
    _write_credentials(config_dir, expires_at=time.time() * 1000)

    findings = doctor.run_checks()

    assert any(f.name == "access token" and f.severity == doctor.WARN for f in findings)


def test_one_failing_check_does_not_abort_the_report(setup_paths, monkeypatch):
    def explode():
        raise RuntimeError(FAKE_ACCESS_TOKEN)

    monkeypatch.setattr(doctor, "check_database", explode)

    findings = doctor.run_checks()

    assert any(f.severity == doctor.FAIL and "could not run" in f.detail for f in findings)
    # The other checks still ran.
    assert any(f.name == "config path" for f in findings)
    # An exception message can be built from file content, so only the type is
    # reported - never str(e).
    assert all(FAKE_ACCESS_TOKEN not in f"{f.detail} {f.fix or ''}" for f in findings)


def test_survives_a_corrupt_database(setup_paths):
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    db_path.write_text("this is not a sqlite database")

    findings = doctor.run_checks()

    assert any(f.severity == doctor.FAIL and "database" in f.name.lower() for f in findings)


def test_reports_a_failed_integrity_check(setup_paths, monkeypatch):
    """A file that opens cleanly but reports corruption must still fail.

    Page-level damage makes `PRAGMA integrity_check` raise (covered above), so
    the branch that reads its *result* is reached only for the corruption
    classes SQLite describes rather than rejects. Driving the pragma directly
    is what pins that contract: anything other than "ok" is a failure.
    """
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    conn.close()

    class ReportsCorruption:
        """Delegates to the real connection, but says the database is damaged."""

        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, *args):
            if "integrity_check" in sql:
                return _FakeCursor(("row 42 missing from index idx_sleep_date",))
            return self._conn.execute(sql, *args)

    real_open = doctor._open_db_readonly

    @contextmanager
    def open_reporting_corruption(path):
        with real_open(path) as conn:
            yield ReportsCorruption(conn)

    monkeypatch.setattr(doctor, "_open_db_readonly", open_reporting_corruption)

    findings = doctor.run_checks()

    assert any(f.severity == doctor.FAIL and "database" in f.name.lower() for f in findings)


# --- Individual checks ---


def test_flags_offline_env_var_that_parses_as_off(setup_paths, monkeypatch):
    """`FITBIT_MCP_OFFLINE=ture` is falsy and silently disables offline mode."""
    monkeypatch.setenv("FITBIT_MCP_OFFLINE", "ture")

    findings = doctor.run_checks()

    assert any("FITBIT_MCP_OFFLINE" in f.detail and f.severity == doctor.WARN for f in findings)


def test_does_not_flag_a_valid_offline_value(setup_paths, monkeypatch):
    monkeypatch.setenv("FITBIT_MCP_OFFLINE", "1")
    monkeypatch.setattr("fitbit_mcp.config.OFFLINE_MODE", True)

    findings = doctor.run_checks()

    assert not any("parses as OFF" in f.detail for f in findings)


def test_detects_a_missing_schema_column(setup_paths):
    """_migrate covers two columns; any other drift must still be reported."""
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    conn.execute("DROP TABLE spo2")
    conn.execute("CREATE TABLE spo2 (date TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    findings = doctor.run_checks()

    assert any("spo2" in f.detail and f.severity == doctor.FAIL for f in findings)


def test_reports_silent_sync_failure_from_sync_log(setup_paths):
    """The mode behind a silent outage: cache served, auth failing, no error."""
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    db.log_sync(conn, "sleep", "auth_error", 0, notes="auth: token refresh failed")
    conn.commit()
    conn.close()

    findings = doctor.run_checks()

    # Assert on the named check, not on a substring: "auth" also appears in the
    # headless-browser warning, which fires on any CI runner and would let this
    # pass with the sync-log check deleted entirely.
    assert any(f.name == "sync log" and f.severity == doctor.FAIL for f in findings)


def test_healthy_setup_reports_no_failures(setup_paths):
    config_dir, db_path = setup_paths
    _write_credentials(config_dir)
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    db.log_sync(conn, "sleep", "ok", 1)
    conn.commit()
    conn.close()

    findings = doctor.run_checks()

    assert not [f for f in findings if f.severity == doctor.FAIL]


def test_exit_code_is_zero_when_healthy(setup_paths, capsys):
    config_dir, db_path = setup_paths
    _write_credentials(config_dir)
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    db.log_sync(conn, "sleep", "ok", 1)
    conn.commit()
    conn.close()

    assert doctor.run_doctor() == 0


def test_exit_code_is_nonzero_when_broken(setup_paths, capsys):
    assert doctor.run_doctor() != 0


def test_classifies_a_google_client_id(setup_paths):
    """After the Sept 2026 turndown, a Fitbit-shaped id in the config is the bug."""
    config_dir, _db_path = setup_paths
    config_dir.mkdir(parents=True)
    (config_dir / "fitbit_config.json").write_text(
        json.dumps({"client_id": "1234-abc.apps.googleusercontent.com"})
    )

    findings = doctor.run_checks()

    assert any("Google" in f.detail for f in findings)


def test_reports_an_expired_access_token_without_calling_the_network(setup_paths, monkeypatch):
    config_dir, _db_path = setup_paths
    _write_credentials(config_dir, expires_at=time.time() - 60)

    def fail_on_network(*_args, **_kwargs):
        raise AssertionError("doctor made a network call")

    monkeypatch.setattr("urllib.request.urlopen", fail_on_network)

    findings = doctor.run_checks()

    assert any("expired" in f.detail.lower() for f in findings)


def test_reports_database_freshness(setup_paths):
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    db.save_sleep(conn, {"date": "2026-03-10", "total_minutes": 420, "efficiency": 90})
    conn.commit()
    conn.close()

    findings = doctor.run_checks()

    assert any("2026-03-10" in f.detail for f in findings)


def test_opens_the_database_read_only(setup_paths):
    """A read-only open is what guarantees the no-mutation property above."""
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    conn.close()

    with doctor._open_db_readonly(db_path) as ro:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("CREATE TABLE should_not_work (x INTEGER)")


def test_read_only_open_survives_a_path_needing_uri_escaping(tmp_path):
    """The path goes into a URI, so `#` would otherwise start a fragment.

    Unescaped, `?mode=ro` lands inside that fragment and is ignored, handing
    back a writable connection to a truncated path - which also creates a
    stray file. Both invariants of this module depend on the escaping.
    """
    awkward = tmp_path / "weird #dir"
    awkward.mkdir()
    db_path = awkward / "fitbit.db"
    db.get_db(db_path).close()

    with doctor._open_db_readonly(db_path) as ro:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("CREATE TABLE should_not_work (x INTEGER)")
        assert ro.execute("SELECT COUNT(*) FROM sleep").fetchone()[0] == 0

    assert not (tmp_path / "weird ").exists()


def test_creates_nothing_under_a_path_needing_uri_escaping(tmp_path, monkeypatch):
    db_path = tmp_path / "weird #dir" / "fitbit.db"
    monkeypatch.setattr("fitbit_mcp.config.CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(
        "fitbit_mcp.config.FITBIT_CONFIG_PATH", tmp_path / "config" / "fitbit_config.json"
    )
    monkeypatch.setattr(
        "fitbit_mcp.config.FITBIT_TOKENS_PATH", tmp_path / "config" / "fitbit_tokens.json"
    )
    monkeypatch.setattr("fitbit_mcp.config.DB_PATH", db_path)
    monkeypatch.setattr("fitbit_mcp.config.OFFLINE_MODE", False)

    doctor.run_checks()

    assert list(tmp_path.iterdir()) == []


def test_self_healing_schema_drift_is_not_reported(setup_paths):
    """db._migrate adds this column on the next open, so it is not a fault.

    Reporting it would attach the "re-create and re-import" remedy and send a
    user to destroy a cache that repairs itself.
    """
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    conn.execute("ALTER TABLE sleep DROP COLUMN sessions")
    conn.commit()
    conn.close()

    findings = doctor.run_checks()

    assert not [f for f in findings if f.name == "schema" and f.severity == doctor.FAIL]


def test_offline_host_with_a_read_only_cache_is_healthy(setup_paths, monkeypatch):
    """One host syncs and the rest read: the documented multi-host layout."""
    _config_dir, db_path = setup_paths
    monkeypatch.setattr("fitbit_mcp.config.OFFLINE_MODE", True)
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    db.save_sleep(conn, {"date": date.today().isoformat(), "total_minutes": 420, "efficiency": 90})
    db.log_sync(conn, "sleep", "ok", 1)
    conn.commit()
    conn.close()
    db_path.chmod(0o444)

    findings = doctor.run_checks()

    assert not [f for f in findings if f.severity != doctor.OK]


def test_offline_host_does_not_blame_itself_for_a_peers_sync_failure(setup_paths, monkeypatch):
    _config_dir, db_path = setup_paths
    monkeypatch.setattr("fitbit_mcp.config.OFFLINE_MODE", True)
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    db.log_sync(conn, "sleep", "auth_error", 0, notes="auth: token refresh failed")
    conn.commit()
    conn.close()

    findings = doctor.run_checks()
    sync_log = [f for f in findings if f.name == "sync log"]

    assert sync_log and sync_log[0].severity == doctor.WARN
    assert "syncing host" in sync_log[0].detail


def test_a_type_that_recovered_is_not_still_reported_as_failing(setup_paths):
    _config_dir, db_path = setup_paths
    _write_credentials(_config_dir)
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    db.log_sync(conn, "sleep", "auth_error", 0, notes="auth: token refresh failed")
    db.log_sync(conn, "sleep", "ok", 5)
    conn.commit()
    conn.close()

    findings = doctor.run_checks()

    assert not [f for f in findings if f.name == "sync log" and f.severity == doctor.FAIL]


def test_warns_when_the_cache_has_stopped_updating(setup_paths):
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    stale = (date.today() - timedelta(days=30)).isoformat()
    db.save_sleep(conn, {"date": stale, "total_minutes": 420, "efficiency": 90})
    conn.commit()
    conn.close()

    findings = doctor.run_checks()

    assert any(f.name == "cache" and f.severity == doctor.WARN for f in findings)


def test_a_current_cache_is_not_called_stale(setup_paths):
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    db.save_sleep(conn, {"date": date.today().isoformat(), "total_minutes": 420, "efficiency": 90})
    conn.commit()
    conn.close()

    findings = doctor.run_checks()

    assert any(f.name == "cache" and f.severity == doctor.OK for f in findings)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permission bits")
def test_reports_an_unwritable_token_file(setup_paths):
    """The refresh rotates server-side before the save, so a failed write
    leaves no usable token anywhere - worth catching before it happens."""
    config_dir, _db_path = setup_paths
    _write_credentials(config_dir)
    (config_dir / "fitbit_tokens.json").chmod(0o444)

    findings = doctor.run_checks()

    assert any(f.name == "credentials" and f.severity == doctor.FAIL for f in findings)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permission bits")
def test_a_read_only_config_directory_is_not_a_problem(setup_paths):
    """auth.py rewrites the token file in place, so only the file must be writable."""
    config_dir, _db_path = setup_paths
    _write_credentials(config_dir)
    config_dir.chmod(0o555)
    try:
        findings = doctor.run_checks()
    finally:
        config_dir.chmod(0o755)

    assert not [f for f in findings if f.name == "credentials" and f.severity == doctor.FAIL]


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_recognised_off_values_are_not_reported_as_typos(setup_paths, monkeypatch, value):
    monkeypatch.setenv("FITBIT_MCP_OFFLINE", value)

    findings = doctor.run_checks()

    assert not [f for f in findings if f.name == "offline mode" and f.severity != doctor.OK]


def test_reports_a_rate_limited_sync(setup_paths):
    _config_dir, db_path = setup_paths
    _write_credentials(_config_dir)
    db_path.parent.mkdir(parents=True)
    conn = db.get_db(db_path)
    db.log_sync(conn, "sleep", "partial", 0, notes="rate limited")
    conn.commit()
    conn.close()

    findings = doctor.run_checks()

    assert any(f.name == "sync log" and f.severity == doctor.WARN for f in findings)


def test_absent_tables_are_reported_without_claiming_the_schema_matches(setup_paths):
    """An empty file has no tables at all; "matches this version" would be false."""
    _config_dir, db_path = setup_paths
    db_path.parent.mkdir(parents=True)
    db_path.touch()

    findings = doctor.run_checks()
    schema = [f for f in findings if f.name == "schema"]

    assert schema and all(f.severity != doctor.OK for f in schema)


def test_read_only_open_handles_a_non_utf8_path(tmp_path):
    """Such a name reaches Python as surrogate escapes, which `quote` refuses.

    Encoding the path through os.fsencode is what keeps this working; passing
    the str straight to `quote` raises UnicodeEncodeError.
    """
    awkward = tmp_path / os.fsdecode(b"raw\xff name")
    try:
        awkward.mkdir()
    except (UnicodeEncodeError, OSError):
        pytest.skip("filesystem rejects non-UTF-8 names")
    db_path = awkward / "fitbit.db"
    db.get_db(db_path).close()

    with doctor._open_db_readonly(db_path) as ro:
        assert ro.execute("SELECT COUNT(*) FROM sleep").fetchone()[0] == 0


def test_read_only_open_handles_a_path_with_a_percent_sign(tmp_path):
    """Guards the double-encoding class that the escaping fix could introduce."""
    awkward = tmp_path / "with%25pct"
    awkward.mkdir()
    db_path = awkward / "fitbit.db"
    db.get_db(db_path).close()

    with doctor._open_db_readonly(db_path) as ro:
        assert ro.execute("SELECT COUNT(*) FROM sleep").fetchone()[0] == 0


def test_warns_when_the_token_file_is_older_than_the_refresh_lifetime(setup_paths):
    config_dir, _db_path = setup_paths
    _write_credentials(config_dir)
    tokens = config_dir / "fitbit_tokens.json"
    ancient = time.time() - timedelta(days=200).total_seconds()
    os.utime(tokens, (ancient, ancient))

    findings = doctor.run_checks()

    assert any(f.name == "refresh token" and f.severity == doctor.WARN for f in findings)
