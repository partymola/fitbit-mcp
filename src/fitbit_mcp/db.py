"""SQLite database schema and helpers for the Fitbit local cache."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH

# Changing this? Copy the outgoing schema into tests/schema_baselines/ and add
# the migration - see AGENTS.md, "Seams the suite does not cross".
SCHEMA = """
CREATE TABLE IF NOT EXISTS heart_rate (
    date TEXT PRIMARY KEY,
    resting_hr INTEGER,
    zones TEXT,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS activity (
    date TEXT PRIMARY KEY,
    steps INTEGER,
    calories_out INTEGER,
    active_minutes INTEGER,
    very_active_minutes INTEGER,
    fairly_active_minutes INTEGER,
    lightly_active_minutes INTEGER,
    sedentary_minutes INTEGER,
    floors INTEGER,
    distance_km REAL,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS exercises (
    log_id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    name TEXT,
    duration_min INTEGER,
    calories INTEGER,
    avg_hr INTEGER,
    steps INTEGER,
    distance_km REAL,
    distance_unit TEXT,
    start_time TEXT,
    source TEXT,
    log_type TEXT,
    provider TEXT
);

CREATE INDEX IF NOT EXISTS idx_exercises_date ON exercises(date);

CREATE TABLE IF NOT EXISTS sleep (
    date TEXT PRIMARY KEY,
    total_minutes INTEGER,
    efficiency INTEGER,
    start_time TEXT,
    end_time TEXT,
    deep_minutes INTEGER,
    light_minutes INTEGER,
    rem_minutes INTEGER,
    wake_minutes INTEGER,
    sessions INTEGER,
    sleep_period_minutes INTEGER,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS weight (
    date TEXT PRIMARY KEY,
    weight_kg REAL,
    bmi REAL,
    fat_pct REAL,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS spo2 (
    date TEXT PRIMARY KEY,
    avg REAL,
    min REAL,
    max REAL,
    avg_ci_low REAL,
    avg_ci_high REAL,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS hrv (
    date TEXT PRIMARY KEY,
    daily_rmssd REAL,
    deep_rmssd REAL,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS azm (
    date TEXT PRIMARY KEY,
    total_minutes INTEGER,
    fat_burn_minutes INTEGER,
    cardio_minutes INTEGER,
    peak_minutes INTEGER,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS breathing_rate (
    date TEXT PRIMARY KEY,
    breaths_per_min REAL,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS skin_temperature (
    date TEXT PRIMARY KEY,
    nightly_relative REAL,
    log_type TEXT,
    nightly_absolute REAL,
    baseline REAL,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS core_temperature (
    datetime TEXT NOT NULL,
    date TEXT NOT NULL,
    temp_celsius REAL,
    provider TEXT,
    PRIMARY KEY (datetime, temp_celsius)
);

CREATE INDEX IF NOT EXISTS idx_core_temperature_date ON core_temperature(date);

CREATE TABLE IF NOT EXISTS cardio_fitness (
    date TEXT PRIMARY KEY,
    vo2_max_low REAL,
    vo2_max_high REAL,
    vo2_max REAL,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS food_log (
    date TEXT PRIMARY KEY,
    calories_in INTEGER,
    water_ml REAL,
    provider TEXT
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    synced_at TEXT NOT NULL,
    data_type TEXT NOT NULL,
    status TEXT NOT NULL,
    records_added INTEGER,
    notes TEXT,
    last_date_attempted TEXT
);
"""


# Every column added to a table after that table shipped, so an existing
# database gains it on open. A column here and not in SCHEMA, or the reverse,
# fails TestTheMigrationLockstep - see AGENTS.md.
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("sync_log", "last_date_attempted", "TEXT"),
    ("sleep", "sessions", "INTEGER"),
    ("sleep", "sleep_period_minutes", "INTEGER"),
    ("spo2", "avg_ci_low", "REAL"),
    ("spo2", "avg_ci_high", "REAL"),
    ("cardio_fitness", "vo2_max", "REAL"),
    ("skin_temperature", "nightly_absolute", "REAL"),
    ("skin_temperature", "baseline", "REAL"),
    ("activity", "provider", "TEXT"),
    ("azm", "provider", "TEXT"),
    ("breathing_rate", "provider", "TEXT"),
    ("cardio_fitness", "provider", "TEXT"),
    ("core_temperature", "provider", "TEXT"),
    ("exercises", "provider", "TEXT"),
    ("food_log", "provider", "TEXT"),
    ("heart_rate", "provider", "TEXT"),
    ("hrv", "provider", "TEXT"),
    ("skin_temperature", "provider", "TEXT"),
    ("sleep", "provider", "TEXT"),
    ("spo2", "provider", "TEXT"),
    ("weight", "provider", "TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply additive schema migrations to older DBs. Idempotent."""
    for table, column, declaration in MIGRATIONS:
        present = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    conn.commit()


def get_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a database connection and ensure the schema exists."""
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# --- Save helpers ---

# The conflict target for each table an upsert writes. core_temperature is
# absent deliberately: its primary key is (datetime, temp_celsius), so a
# changed reading is a new row rather than a correction, and it keeps the
# INSERT OR IGNORE below. sync_log is append-only.
_UPSERT_KEYS: dict[str, tuple[str, ...]] = {
    "heart_rate": ("date",),
    "activity": ("date",),
    "exercises": ("log_id",),
    "sleep": ("date",),
    "weight": ("date",),
    "spo2": ("date",),
    "hrv": ("date",),
    "azm": ("date",),
    "breathing_rate": ("date",),
    "skin_temperature": ("date",),
    "cardio_fitness": ("date",),
    "food_log": ("date",),
}


def _upsert(conn: sqlite3.Connection, table: str, row: dict) -> None:
    """Write `row`, leaving the columns it does not name as they were.

    Omitting a column and passing it as None are different instructions.
    The second writes NULL, which is how a value a provider has withdrawn
    gets cleared.
    """
    keys = _UPSERT_KEYS[table]
    known = {r[1] for r in conn.execute(f"PRAGMA table_info('{table}')")}
    unknown = sorted(set(row) - known)
    if unknown:
        raise ValueError(f"{table} has no column(s) {', '.join(unknown)}")
    absent = [k for k in keys if row.get(k) is None]
    if absent:
        raise ValueError(f"{table} needs {', '.join(absent)} to identify the row")

    columns = list(row)
    updatable = [c for c in columns if c not in keys]
    if not updatable:
        # A row carrying nothing but its key has nothing to store, and inserting
        # it would date-stamp a day whose values never arrived.
        return

    # Nothing reaches this SQL text unchecked: every name is a column the table has.
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(':' + c for c in columns)}) "
        f"ON CONFLICT({', '.join(keys)}) DO UPDATE SET "
        + ", ".join(f"{c} = excluded.{c}" for c in updatable),
        row,
    )


def save_heart_rate(conn: sqlite3.Connection, date: str, resting_hr: int | None, zones: list):
    _upsert(
        conn,
        "heart_rate",
        {"date": date, "resting_hr": resting_hr, "zones": json.dumps(zones)},
    )


def save_activity(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "activity", row)


def save_exercise(conn: sqlite3.Connection, log_id: str, row: dict):
    _upsert(conn, "exercises", {"log_id": log_id, **row})


def save_sleep(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "sleep", row)


def save_weight(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "weight", row)


def save_spo2(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "spo2", row)


def save_hrv(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "hrv", row)


def save_azm(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "azm", row)


def save_breathing_rate(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "breathing_rate", row)


def save_skin_temperature(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "skin_temperature", row)


def save_core_temperature(conn: sqlite3.Connection, row: dict) -> int:
    """Insert one manually-logged core-temperature reading. Returns rows inserted (0 or 1).

    Keyed by (datetime, temp_celsius), not date: core temperatures are logged by
    hand and a day may hold several readings. Fitbit timestamps are only
    second-resolution, so two genuinely distinct readings can share a timestamp -
    keying on the (timestamp, value) pair keeps both, while INSERT OR IGNORE still
    de-duplicates exact repeats idempotently when a boundary day is re-synced.
    """
    cur = conn.execute(
        """INSERT OR IGNORE INTO core_temperature (datetime, date, temp_celsius)
        VALUES (:datetime, :date, :temp_celsius)""",
        row,
    )
    return cur.rowcount


def save_cardio_fitness(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "cardio_fitness", row)


def save_food_log(conn: sqlite3.Connection, row: dict):
    _upsert(conn, "food_log", row)


def log_sync(
    conn: sqlite3.Connection,
    data_type: str,
    status: str,
    records_added: int = 0,
    notes: str = "",
    last_date_attempted: str | None = None,
):
    conn.execute(
        """INSERT INTO sync_log
            (synced_at, data_type, status, records_added, notes, last_date_attempted)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            data_type,
            status,
            records_added,
            notes,
            last_date_attempted,
        ),
    )
    conn.commit()


# Allowlist mapping data_type names to their table names. Used in get_last_synced_date
# to safely interpolate table names into SQL (SQLite doesn't support parameterised table names).
_DATA_TABLE_MAP: dict[str, str] = {
    "heart_rate": "heart_rate",
    "activity": "activity",
    "exercises": "exercises",
    "sleep": "sleep",
    "weight": "weight",
    "spo2": "spo2",
    "hrv": "hrv",
    "azm": "azm",
    "breathing_rate": "breathing_rate",
    "skin_temperature": "skin_temperature",
    "core_temperature": "core_temperature",
    "cardio_fitness": "cardio_fitness",
    "food_log": "food_log",
}


def get_last_sync_time(conn: sqlite3.Connection, data_type: str) -> datetime | None:
    """Return the timestamp of the most recent successful sync for a data type."""
    row = conn.execute(
        "SELECT MAX(synced_at) AS t FROM sync_log WHERE data_type = ? AND status = 'ok'",
        (data_type,),
    ).fetchone()
    if row and row["t"]:
        return datetime.fromisoformat(row["t"])
    return None


def get_last_synced_date(conn: sqlite3.Connection, data_type: str) -> str | None:
    """Return the most recent date synced for a data type, from the actual data table."""
    table = _DATA_TABLE_MAP.get(data_type)
    if table is None:
        return None
    # table is from the hardcoded allowlist above - safe to interpolate
    row = conn.execute(f"SELECT MAX(date) AS d FROM {table}").fetchone()
    return row["d"] if row else None


def get_last_attempted_date(conn: sqlite3.Connection, data_type: str) -> str | None:
    """Return the most recent end-date a successful sync attempted to reach.

    Distinct from `get_last_synced_date`, which only sees days that produced
    a row. For sparse-data types (e.g. food_log, skin_temperature) where
    many days legitimately produce no data, the attempted-date is what we
    really want to advance forward on the next sync, otherwise we'd re-query
    every empty day forever.
    """
    row = conn.execute(
        "SELECT MAX(last_date_attempted) AS d FROM sync_log WHERE data_type = ? AND status = 'ok'",
        (data_type,),
    ).fetchone()
    return row["d"] if row and row["d"] else None


# --- Query helpers ---


def _rows_to_dicts(rows) -> list[dict]:
    result = []
    for r in rows:
        d = dict(r)
        # Decode JSON blobs
        if "zones" in d and d["zones"]:
            try:
                d["zones"] = json.loads(d["zones"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def query_heart_rate(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM heart_rate WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_activity(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM activity WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_exercises(
    conn: sqlite3.Connection, start_date: str, end_date: str, exercise_type: str | None = None
) -> list[dict]:
    if exercise_type:
        rows = conn.execute(
            "SELECT * FROM exercises WHERE date >= ? AND date <= ? "
            "AND LOWER(name) LIKE ? ORDER BY date, start_time",
            (start_date, end_date, f"%{exercise_type.lower()}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM exercises WHERE date >= ? AND date <= ? ORDER BY date, start_time",
            (start_date, end_date),
        ).fetchall()
    return _rows_to_dicts(rows)


def query_sleep(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM sleep WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_weight(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM weight WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_spo2(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM spo2 WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_hrv(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM hrv WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_azm(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM azm WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_breathing_rate(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM breathing_rate WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_skin_temperature(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM skin_temperature WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_core_temperature(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM core_temperature WHERE date >= ? AND date <= ? "
        "ORDER BY datetime, temp_celsius",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_cardio_fitness(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM cardio_fitness WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_food_log(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM food_log WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date),
    ).fetchall()
    return _rows_to_dicts(rows)
