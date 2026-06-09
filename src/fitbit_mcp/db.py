"""SQLite database schema and helpers for the Fitbit local cache."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS heart_rate (
    date TEXT PRIMARY KEY,
    resting_hr INTEGER,
    zones TEXT
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
    distance_km REAL
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
    log_type TEXT
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
    sessions INTEGER
);

CREATE TABLE IF NOT EXISTS weight (
    date TEXT PRIMARY KEY,
    weight_kg REAL,
    bmi REAL,
    fat_pct REAL
);

CREATE TABLE IF NOT EXISTS spo2 (
    date TEXT PRIMARY KEY,
    avg REAL,
    min REAL,
    max REAL
);

CREATE TABLE IF NOT EXISTS hrv (
    date TEXT PRIMARY KEY,
    daily_rmssd REAL,
    deep_rmssd REAL
);

CREATE TABLE IF NOT EXISTS azm (
    date TEXT PRIMARY KEY,
    total_minutes INTEGER,
    fat_burn_minutes INTEGER,
    cardio_minutes INTEGER,
    peak_minutes INTEGER
);

CREATE TABLE IF NOT EXISTS breathing_rate (
    date TEXT PRIMARY KEY,
    breaths_per_min REAL
);

CREATE TABLE IF NOT EXISTS skin_temperature (
    date TEXT PRIMARY KEY,
    nightly_relative REAL,
    log_type TEXT
);

CREATE TABLE IF NOT EXISTS cardio_fitness (
    date TEXT PRIMARY KEY,
    vo2_max_low REAL,
    vo2_max_high REAL
);

CREATE TABLE IF NOT EXISTS food_log (
    date TEXT PRIMARY KEY,
    calories_in INTEGER,
    water_ml REAL
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


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply additive schema migrations to older DBs. Idempotent."""
    sync_log_cols = {r["name"] for r in conn.execute("PRAGMA table_info(sync_log)").fetchall()}
    if "last_date_attempted" not in sync_log_cols:
        conn.execute("ALTER TABLE sync_log ADD COLUMN last_date_attempted TEXT")
        conn.commit()

    sleep_cols = {r["name"] for r in conn.execute("PRAGMA table_info(sleep)").fetchall()}
    if "sessions" not in sleep_cols:
        conn.execute("ALTER TABLE sleep ADD COLUMN sessions INTEGER")
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


def save_heart_rate(conn: sqlite3.Connection, date: str, resting_hr: int | None, zones: list):
    conn.execute(
        "INSERT OR REPLACE INTO heart_rate (date, resting_hr, zones) VALUES (?, ?, ?)",
        (date, resting_hr, json.dumps(zones)),
    )


def save_activity(conn: sqlite3.Connection, row: dict):
    conn.execute(
        """INSERT OR REPLACE INTO activity
        (date, steps, calories_out, active_minutes, very_active_minutes,
         fairly_active_minutes, lightly_active_minutes, sedentary_minutes,
         floors, distance_km)
        VALUES (:date, :steps, :calories_out, :active_minutes, :very_active_minutes,
                :fairly_active_minutes, :lightly_active_minutes, :sedentary_minutes,
                :floors, :distance_km)""",
        row,
    )


def save_exercise(conn: sqlite3.Connection, log_id: str, row: dict):
    conn.execute(
        """INSERT OR REPLACE INTO exercises
        (log_id, date, name, duration_min, calories, avg_hr, steps,
         distance_km, distance_unit, start_time, source, log_type)
        VALUES (:log_id, :date, :name, :duration_min, :calories, :avg_hr, :steps,
                :distance_km, :distance_unit, :start_time, :source, :log_type)""",
        {"log_id": log_id, **row},
    )


def save_sleep(conn: sqlite3.Connection, row: dict):
    # Default every optional column via .get() so callers that supply only a
    # subset (e.g. the Takeout importer) store NULL rather than raising.
    params = {
        "date": row["date"],
        "total_minutes": row.get("total_minutes"),
        "efficiency": row.get("efficiency"),
        "start_time": row.get("start_time"),
        "end_time": row.get("end_time"),
        "deep_minutes": row.get("deep_minutes"),
        "light_minutes": row.get("light_minutes"),
        "rem_minutes": row.get("rem_minutes"),
        "wake_minutes": row.get("wake_minutes"),
        "sessions": row.get("sessions"),
    }
    conn.execute(
        """INSERT OR REPLACE INTO sleep
        (date, total_minutes, efficiency, start_time, end_time,
         deep_minutes, light_minutes, rem_minutes, wake_minutes, sessions)
        VALUES (:date, :total_minutes, :efficiency, :start_time, :end_time,
                :deep_minutes, :light_minutes, :rem_minutes, :wake_minutes, :sessions)""",
        params,
    )


def save_weight(conn: sqlite3.Connection, row: dict):
    conn.execute(
        """INSERT OR REPLACE INTO weight
        (date, weight_kg, bmi, fat_pct)
        VALUES (:date, :weight_kg, :bmi, :fat_pct)""",
        row,
    )


def save_spo2(conn: sqlite3.Connection, row: dict):
    conn.execute(
        "INSERT OR REPLACE INTO spo2 (date, avg, min, max) VALUES (:date, :avg, :min, :max)",
        row,
    )


def save_hrv(conn: sqlite3.Connection, row: dict):
    conn.execute(
        """INSERT OR REPLACE INTO hrv
        (date, daily_rmssd, deep_rmssd)
        VALUES (:date, :daily_rmssd, :deep_rmssd)""",
        row,
    )


def save_azm(conn: sqlite3.Connection, row: dict):
    conn.execute(
        """INSERT OR REPLACE INTO azm
        (date, total_minutes, fat_burn_minutes, cardio_minutes, peak_minutes)
        VALUES (:date, :total_minutes, :fat_burn_minutes, :cardio_minutes, :peak_minutes)""",
        row,
    )


def save_breathing_rate(conn: sqlite3.Connection, row: dict):
    conn.execute(
        """INSERT OR REPLACE INTO breathing_rate
        (date, breaths_per_min)
        VALUES (:date, :breaths_per_min)""",
        row,
    )


def save_skin_temperature(conn: sqlite3.Connection, row: dict):
    conn.execute(
        """INSERT OR REPLACE INTO skin_temperature (date, nightly_relative, log_type)
        VALUES (:date, :nightly_relative, :log_type)""",
        row,
    )


def save_cardio_fitness(conn: sqlite3.Connection, row: dict):
    conn.execute(
        """INSERT OR REPLACE INTO cardio_fitness (date, vo2_max_low, vo2_max_high)
        VALUES (:date, :vo2_max_low, :vo2_max_high)""",
        row,
    )


def save_food_log(conn: sqlite3.Connection, row: dict):
    conn.execute(
        """INSERT OR REPLACE INTO food_log
        (date, calories_in, water_ml)
        VALUES (:date, :calories_in, :water_ml)""",
        row,
    )


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
