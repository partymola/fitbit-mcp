"""One-time import of existing Fitbit JSON data files into the SQLite cache.

Usage:
    fitbit-mcp import --data-dir ~/claude/personal/fitbit/data/
"""

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def run_import(data_dir: Path):
    """Import all JSON data files from data_dir into the SQLite database."""
    from . import db

    if not data_dir.exists():
        print(f"Error: data directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    conn = db.get_db()
    total_imported = 0

    # --- heart_rate.json ---
    hr_file = data_dir / "heart_rate.json"
    if hr_file.exists():
        data = json.loads(hr_file.read_text())
        count = 0
        for ds, entry in data.items():
            if ds.startswith("_"):
                continue
            db.save_heart_rate(
                conn, ds,
                entry.get("resting_hr"),
                entry.get("heart_rate_zones", []),
            )
            count += 1
        conn.commit()
        db.log_sync(conn, "heart_rate", "import", count, f"imported from {hr_file}")
        print(f"  heart_rate: {count} days")
        total_imported += count
    else:
        print("  heart_rate.json: not found, skipping")

    # --- activity.json ---
    act_file = data_dir / "activity.json"
    if act_file.exists():
        data = json.loads(act_file.read_text())
        count = 0
        for ds, entry in data.items():
            if ds.startswith("_"):
                continue
            db.save_activity(conn, {
                "date": ds,
                "steps": entry.get("steps"),
                "calories_out": entry.get("calories_out"),
                "active_minutes": entry.get("active_minutes"),
                "very_active_minutes": entry.get("very_active_minutes"),
                "fairly_active_minutes": entry.get("fairly_active_minutes"),
                "lightly_active_minutes": entry.get("lightly_active_minutes"),
                "sedentary_minutes": entry.get("sedentary_minutes"),
                "floors": entry.get("floors"),
                "distance_km": entry.get("distance_km"),
            })
            count += 1
        conn.commit()
        db.log_sync(conn, "activity", "import", count, f"imported from {act_file}")
        print(f"  activity: {count} days")
        total_imported += count
    else:
        print("  activity.json: not found, skipping")

    # --- exercises.json ---
    ex_file = data_dir / "exercises.json"
    if ex_file.exists():
        data = json.loads(ex_file.read_text())
        count = 0
        for log_id, entry in data.items():
            if log_id.startswith("_"):
                continue
            db.save_exercise(conn, log_id, {
                "date": entry.get("date", ""),
                "name": entry.get("name"),
                "duration_min": entry.get("duration_min"),
                "calories": entry.get("calories"),
                "avg_hr": entry.get("avg_hr"),
                "steps": entry.get("steps"),
                "distance_km": entry.get("distance_km"),
                "distance_unit": entry.get("distance_unit"),
                "start_time": entry.get("start_time"),
                "source": entry.get("source"),
                "log_type": entry.get("log_type"),
            })
            count += 1
        conn.commit()
        db.log_sync(conn, "exercises", "import", count, f"imported from {ex_file}")
        print(f"  exercises: {count} entries")
        total_imported += count
    else:
        print("  exercises.json: not found, skipping")

    # --- sleep.json ---
    sleep_file = data_dir / "sleep.json"
    if sleep_file.exists():
        data = json.loads(sleep_file.read_text())
        count = 0
        for ds, entry in data.items():
            if ds.startswith("_"):
                continue
            db.save_sleep(conn, {
                "date": ds,
                "total_minutes": entry.get("total_minutes"),
                "efficiency": entry.get("efficiency"),
                "start_time": entry.get("start_time"),
                "end_time": entry.get("end_time"),
                "deep_minutes": entry.get("deep_minutes"),
                "light_minutes": entry.get("light_minutes"),
                "rem_minutes": entry.get("rem_minutes"),
                "wake_minutes": entry.get("wake_minutes"),
            })
            count += 1
        conn.commit()
        db.log_sync(conn, "sleep", "import", count, f"imported from {sleep_file}")
        print(f"  sleep: {count} nights")
        total_imported += count
    else:
        print("  sleep.json: not found, skipping")

    # --- weight.json ---
    weight_file = data_dir / "weight.json"
    if weight_file.exists():
        data = json.loads(weight_file.read_text())
        count = 0
        for ds, entry in data.items():
            if ds.startswith("_"):
                continue
            db.save_weight(conn, {
                "date": ds,
                "weight_kg": entry.get("weight_kg"),
                "bmi": entry.get("bmi"),
                "fat_pct": entry.get("fat_pct"),
            })
            count += 1
        conn.commit()
        db.log_sync(conn, "weight", "import", count, f"imported from {weight_file}")
        print(f"  weight: {count} entries")
        total_imported += count
    else:
        print("  weight.json: not found, skipping")

    # --- spo2.json ---
    spo2_file = data_dir / "spo2.json"
    if spo2_file.exists():
        data = json.loads(spo2_file.read_text())
        count = 0
        for ds, entry in data.items():
            if ds.startswith("_"):
                continue
            db.save_spo2(conn, {
                "date": ds,
                "avg": entry.get("avg"),
                "min": entry.get("min"),
                "max": entry.get("max"),
            })
            count += 1
        conn.commit()
        db.log_sync(conn, "spo2", "import", count, f"imported from {spo2_file}")
        print(f"  spo2: {count} nights")
        total_imported += count
    else:
        print("  spo2.json: not found, skipping")

    # --- hrv.json ---
    hrv_file = data_dir / "hrv.json"
    if hrv_file.exists():
        data = json.loads(hrv_file.read_text())
        count = 0
        for ds, entry in data.items():
            if ds.startswith("_"):
                continue
            db.save_hrv(conn, {
                "date": ds,
                "daily_rmssd": entry.get("daily_rmssd"),
                "deep_rmssd": entry.get("deep_rmssd"),
            })
            count += 1
        conn.commit()
        db.log_sync(conn, "hrv", "import", count, f"imported from {hrv_file}")
        print(f"  hrv: {count} nights")
        total_imported += count
    else:
        print("  hrv.json: not found, skipping")

    conn.close()
    print(f"\nImport complete. {total_imported} total records imported.")
    print(f"Database: {db.DB_PATH}")
