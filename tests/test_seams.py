"""Claims no input to the program can falsify.

A behavioural test asks "given this input, what happens". The assertions
here are about the code's structure and its packaging, so nothing you can
feed the server exercises them - which is why each of these survived until
someone went looking. See AGENTS.md, "Seams the suite does not cross".
"""

import ast
import sqlite3
import tomllib
from pathlib import Path

import fitbit_mcp
from fitbit_mcp import db, doctor

_PATH_NAMES = {
    "CONFIG_DIR",
    "DB_PATH",
    "FITBIT_CONFIG_PATH",
    "FITBIT_TOKENS_PATH",
    "data_dir",
    "path",
}
_CLI_ONLY = {"cli.py", "doctor.py", "importer.py"}
_LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception", "log"}


def _shared_sources():
    root = Path(fitbit_mcp.__file__).parent
    return [p for p in sorted(root.rglob("*.py")) if p.name not in _CLI_ONLY]


def test_no_logger_call_in_shared_code_carries_a_path():
    """A CLI subcommand may print a path; shared code may not.

    Server mode writes log lines to stderr, where the MCP client collects
    them, so a log line is closer to a tool response than to a terminal.

    _PATH_NAMES is a blocklist, which is weaker than the whitelist guarding
    setup_auth. It is defensible only because the path identifiers in
    config.py are a small closed set - a new one must be added here.
    """
    offenders = []
    for source in _shared_sources():
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            # Keyed on the logging method, not on how the logger is spelled:
            # `logger.info` and `logging.getLogger(__name__).info` are the
            # same call, and matching the receiver's name misses the second.
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LOG_METHODS
            ):
                continue
            for arg in node.args + [kw.value for kw in node.keywords]:
                if any(name in ast.unparse(arg) for name in _PATH_NAMES):
                    offenders.append(f"{source.name}:{node.lineno} {ast.unparse(node)}")
    assert not offenders, f"log line carries a path: {offenders}"


def test_the_declared_version_and_the_lockfile_agree():
    """Nothing behavioural can see a lockfile left behind by a bump.

    A release does both by hand, and a commit exists in this history
    because one of them was missed.
    """
    root = Path(fitbit_mcp.__file__).parents[2]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    locked = tomllib.loads((root / "uv.lock").read_text())
    ours = [p for p in locked["package"] if p["name"] == "fitbit-mcp"]
    assert ours, "fitbit-mcp is not in uv.lock"
    assert ours[0]["version"] == declared, (
        f"pyproject.toml says {declared}, uv.lock says {ours[0]['version']} - run `uv lock`"
    )


def _columns(conn) -> dict[str, set[str]]:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {t: {r[1] for r in conn.execute(f"PRAGMA table_info('{t}')")} for t in tables}


def _baselines() -> list[Path]:
    """One file per schema this package has released, oldest first.

    A single baseline is not enough. A table absent from it is created whole
    by `CREATE TABLE IF NOT EXISTS`, so a column added to that table needs no
    migration to satisfy the check - while the database of a user who has that
    table and not that column still breaks. Covering every vintage is what
    makes the check say what it claims. Add the outgoing schema here whenever
    SCHEMA changes; never edit one in place.
    """
    found = sorted((Path(__file__).parent / "schema_baselines").glob("*.sql"))
    assert found, "no baselines - the lockstep check would pass on nothing"
    return found


def _built_from(path: Path, baseline: Path) -> dict[str, set[str]]:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(baseline.read_text())
        conn.commit()
        return _columns(conn)
    finally:
        conn.close()


def _current_schema_columns() -> dict[str, set[str]]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(db.SCHEMA)
        return _columns(conn)
    finally:
        conn.close()


class TestTheMigrationLockstep:
    """The lists a schema change has to move together.

    Every test builds its own database, so nothing a user could sync changes
    the answer. Break the lockstep and doctor tells a user with years of
    history to "re-create and re-import" a database that only needed an ALTER.
    """

    def test_every_supported_database_gains_this_versions_schema(self, tmp_path):
        """A column added to SCHEMA reaches an existing database only via _migrate.

        CREATE TABLE IF NOT EXISTS creates whole tables and nothing else, so a
        new column with no ALTER beside it exists on fresh installs only.
        """
        expected = _current_schema_columns()
        for baseline in _baselines():
            path = tmp_path / f"{baseline.stem}.db"
            _built_from(path, baseline)
            conn = db.get_db(path)
            try:
                assert _columns(conn) == expected, baseline.stem
            finally:
                conn.close()

    def test_self_healing_columns_is_exactly_what_migrate_adds(self, tmp_path):
        """doctor excuses a missing column only where _migrate will restore it.

        Too few entries and an ordinary upgrade reports FAIL; too many and a
        column that really is unrepairable is waved through as self-healing.
        """
        added = set()
        for baseline in _baselines():
            path = tmp_path / f"{baseline.stem}.db"
            before = _built_from(path, baseline)
            conn = db.get_db(path)
            try:
                after = _columns(conn)
            finally:
                conn.close()
            # Only tables the baseline had: one it lacked arrives whole, and
            # its columns are not something _migrate added.
            added |= {
                (table, column)
                for table, columns in before.items()
                for column in after[table] - columns
            }
        assert added == doctor._SELF_HEALING_COLUMNS
