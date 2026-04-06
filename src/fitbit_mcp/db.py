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
    wake_minutes INTEGER
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

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    synced_at TEXT NOT NULL,
    data_type TEXT NOT NULL,
    status TEXT NOT NULL,
    records_added INTEGER,
    notes TEXT
);
"""


def get_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a database connection and ensure the schema exists."""
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
    conn.execute(
        """INSERT OR REPLACE INTO sleep
        (date, total_minutes, efficiency, start_time, end_time,
         deep_minutes, light_minutes, rem_minutes, wake_minutes)
        VALUES (:date, :total_minutes, :efficiency, :start_time, :end_time,
                :deep_minutes, :light_minutes, :rem_minutes, :wake_minutes)""",
        row,
    )


def save_weight(conn: sqlite3.Connection, row: dict):
    conn.execute(
        "INSERT OR REPLACE INTO weight (date, weight_kg, bmi, fat_pct) VALUES (:date, :weight_kg, :bmi, :fat_pct)",
        row,
    )


def save_spo2(conn: sqlite3.Connection, row: dict):
    conn.execute(
        "INSERT OR REPLACE INTO spo2 (date, avg, min, max) VALUES (:date, :avg, :min, :max)",
        row,
    )


def save_hrv(conn: sqlite3.Connection, row: dict):
    conn.execute(
        "INSERT OR REPLACE INTO hrv (date, daily_rmssd, deep_rmssd) VALUES (:date, :daily_rmssd, :deep_rmssd)",
        row,
    )


def log_sync(conn: sqlite3.Connection, data_type: str, status: str,
             records_added: int = 0, notes: str = ""):
    conn.execute(
        """INSERT INTO sync_log (synced_at, data_type, status, records_added, notes)
        VALUES (?, ?, ?, ?, ?)""",
        (datetime.now(timezone.utc).isoformat(), data_type, status, records_added, notes),
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


def query_exercises(conn: sqlite3.Connection, start_date: str, end_date: str,
                    exercise_type: str | None = None) -> list[dict]:
    if exercise_type:
        rows = conn.execute(
            "SELECT * FROM exercises WHERE date >= ? AND date <= ? AND LOWER(name) LIKE ? ORDER BY date, start_time",
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
