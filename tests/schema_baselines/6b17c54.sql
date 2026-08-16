-- db.SCHEMA as released in 6b17c54, verbatim. Regenerate, never hand-edit:
--   git show 6b17c54:src/fitbit_mcp/db.py | sed -n '/^SCHEMA = """/,/^"""/p'

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
