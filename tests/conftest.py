"""Shared fixtures for the fitbit-mcp test suite."""

import json
import sqlite3
from pathlib import Path

import pytest

from fitbit_mcp import db


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database with the fitbit schema."""
    db_path = tmp_path / "test_fitbit.db"
    conn = db.get_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def populated_db(tmp_db):
    """Database pre-loaded with sample data across all tables."""
    # Heart rate - 5 days
    for i in range(5):
        db.save_heart_rate(tmp_db, f"2026-03-{10+i:02d}", 60 + i, [
            {"name": "Out of Range", "minutes": 1200, "caloriesOut": 1000, "min": 30, "max": 100},
            {"name": "Fat Burn", "minutes": 30, "caloriesOut": 200, "min": 100, "max": 140},
        ])

    # Activity - 5 days
    for i in range(5):
        db.save_activity(tmp_db, {
            "date": f"2026-03-{10+i:02d}",
            "steps": 8000 + i * 500,
            "calories_out": 2200 + i * 100,
            "active_minutes": 30 + i * 5,
            "very_active_minutes": 15 + i * 2,
            "fairly_active_minutes": 15 + i * 3,
            "lightly_active_minutes": 180 + i * 10,
            "sedentary_minutes": 600 - i * 20,
            "floors": 5 + i,
            "distance_km": 5.0 + i * 0.5,
        })

    # Exercises - 3 sessions
    db.save_exercise(tmp_db, "log001", {
        "date": "2026-03-10", "name": "Walk", "duration_min": 45,
        "calories": 200, "avg_hr": 105, "steps": 5000,
        "distance_km": 3.5, "distance_unit": "Kilometer",
        "start_time": "2026-03-10T08:00:00", "source": "Tracker", "log_type": "auto_detected",
    })
    db.save_exercise(tmp_db, "log002", {
        "date": "2026-03-11", "name": "Cycling", "duration_min": 30,
        "calories": 300, "avg_hr": 130, "steps": None,
        "distance_km": 8.0, "distance_unit": "Kilometer",
        "start_time": "2026-03-11T07:30:00", "source": "Tracker", "log_type": "auto_detected",
    })
    db.save_exercise(tmp_db, "log003", {
        "date": "2026-03-12", "name": "Walk", "duration_min": 60,
        "calories": 250, "avg_hr": 110, "steps": 7000,
        "distance_km": 4.5, "distance_unit": "Kilometer",
        "start_time": "2026-03-12T12:00:00", "source": "Tracker", "log_type": "auto_detected",
    })

    # Sleep - 5 nights
    for i in range(5):
        db.save_sleep(tmp_db, {
            "date": f"2026-03-{10+i:02d}",
            "total_minutes": 420 + i * 10,
            "efficiency": 90 + i,
            "start_time": f"2026-03-{9+i:02d}T23:00:00",
            "end_time": f"2026-03-{10+i:02d}T06:00:00",
            "deep_minutes": 60 + i * 5,
            "light_minutes": 200 + i * 3,
            "rem_minutes": 100 + i * 2,
            "wake_minutes": 60 - i * 5,
        })

    # Weight - 3 entries
    for i in range(3):
        db.save_weight(tmp_db, {
            "date": f"2026-03-{10+i*3:02d}",
            "weight_kg": 80.0 - i * 0.5,
            "bmi": 25.0 - i * 0.2,
            "fat_pct": 20.0 - i * 0.5,
        })

    # SpO2 - 5 nights
    for i in range(5):
        db.save_spo2(tmp_db, {
            "date": f"2026-03-{10+i:02d}",
            "avg": 96.0 + i * 0.2,
            "min": 93.0 + i * 0.3,
            "max": 99.0,
        })

    # HRV - 5 nights
    for i in range(5):
        db.save_hrv(tmp_db, {
            "date": f"2026-03-{10+i:02d}",
            "daily_rmssd": 35.0 + i * 2.0,
            "deep_rmssd": 40.0 + i * 2.5,
        })

    tmp_db.commit()
    return tmp_db
