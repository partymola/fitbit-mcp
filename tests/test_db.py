"""Tests for the SQLite database layer."""

import json

import pytest

from fitbit_mcp import db


class TestSchema:
    """Verify schema creation and table existence."""

    def test_tables_created(self, tmp_db):
        tables = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [t["name"] for t in tables]
        assert "heart_rate" in names
        assert "activity" in names
        assert "exercises" in names
        assert "sleep" in names
        assert "weight" in names
        assert "spo2" in names
        assert "hrv" in names
        assert "sync_log" in names

    def test_exercises_date_index(self, tmp_db):
        indexes = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='exercises'"
        ).fetchall()
        names = [i["name"] for i in indexes]
        assert "idx_exercises_date" in names

    def test_idempotent_schema(self, tmp_db):
        """Calling get_db again shouldn't fail (IF NOT EXISTS)."""
        db.get_db(tmp_db.execute("PRAGMA database_list").fetchone()[2])


class TestSaveAndQuery:
    """Test save + query round-trips for each data type."""

    def test_heart_rate_save_query(self, tmp_db):
        zones = [{"name": "Fat Burn", "minutes": 30}]
        db.save_heart_rate(tmp_db, "2026-03-15", 62, zones)
        tmp_db.commit()

        rows = db.query_heart_rate(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["resting_hr"] == 62
        assert rows[0]["zones"] == zones

    def test_heart_rate_zones_json_roundtrip(self, tmp_db):
        zones = [{"name": "Peak", "minutes": 5, "max": 200}]
        db.save_heart_rate(tmp_db, "2026-03-15", 70, zones)
        tmp_db.commit()
        rows = db.query_heart_rate(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["zones"][0]["max"] == 200

    def test_heart_rate_null_resting(self, tmp_db):
        db.save_heart_rate(tmp_db, "2026-03-15", None, [])
        tmp_db.commit()
        rows = db.query_heart_rate(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["resting_hr"] is None

    def test_activity_save_query(self, tmp_db):
        row = {
            "date": "2026-03-15", "steps": 10000, "calories_out": 2500,
            "active_minutes": 45, "very_active_minutes": 20,
            "fairly_active_minutes": 25, "lightly_active_minutes": 200,
            "sedentary_minutes": 500, "floors": 10, "distance_km": 7.5,
        }
        db.save_activity(tmp_db, row)
        tmp_db.commit()
        rows = db.query_activity(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["steps"] == 10000
        assert rows[0]["distance_km"] == 7.5

    def test_exercise_save_query(self, tmp_db):
        row = {
            "date": "2026-03-15", "name": "Running", "duration_min": 30,
            "calories": 350, "avg_hr": 145, "steps": 4000,
            "distance_km": 5.0, "distance_unit": "Kilometer",
            "start_time": "2026-03-15T07:00:00", "source": "Tracker",
            "log_type": "auto_detected",
        }
        db.save_exercise(tmp_db, "log123", row)
        tmp_db.commit()
        rows = db.query_exercises(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["name"] == "Running"
        assert rows[0]["log_id"] == "log123"

    def test_exercise_type_filter(self, tmp_db):
        db.save_exercise(tmp_db, "log1", {
            "date": "2026-03-15", "name": "Walk", "duration_min": 30,
            "calories": 150, "avg_hr": 100, "steps": 3000,
            "distance_km": 2.0, "distance_unit": "Kilometer",
            "start_time": "2026-03-15T08:00:00", "source": "Tracker", "log_type": "auto_detected",
        })
        db.save_exercise(tmp_db, "log2", {
            "date": "2026-03-15", "name": "Cycling", "duration_min": 45,
            "calories": 400, "avg_hr": 130, "steps": None,
            "distance_km": 12.0, "distance_unit": "Kilometer",
            "start_time": "2026-03-15T17:00:00", "source": "Tracker", "log_type": "auto_detected",
        })
        tmp_db.commit()

        walks = db.query_exercises(tmp_db, "2026-03-15", "2026-03-15", "walk")
        assert len(walks) == 1
        assert walks[0]["name"] == "Walk"

        cycles = db.query_exercises(tmp_db, "2026-03-15", "2026-03-15", "cycling")
        assert len(cycles) == 1

        all_ex = db.query_exercises(tmp_db, "2026-03-15", "2026-03-15")
        assert len(all_ex) == 2

    def test_sleep_save_query(self, tmp_db):
        row = {
            "date": "2026-03-15", "total_minutes": 450, "efficiency": 92,
            "start_time": "2026-03-14T23:00:00", "end_time": "2026-03-15T06:30:00",
            "deep_minutes": 70, "light_minutes": 210, "rem_minutes": 110,
            "wake_minutes": 60,
        }
        db.save_sleep(tmp_db, row)
        tmp_db.commit()
        rows = db.query_sleep(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["efficiency"] == 92

    def test_weight_save_query(self, tmp_db):
        db.save_weight(tmp_db, {"date": "2026-03-15", "weight_kg": 78.5, "bmi": 24.2, "fat_pct": 18.5})
        tmp_db.commit()
        rows = db.query_weight(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["weight_kg"] == 78.5

    def test_spo2_save_query(self, tmp_db):
        db.save_spo2(tmp_db, {"date": "2026-03-15", "avg": 96.5, "min": 93.0, "max": 99.0})
        tmp_db.commit()
        rows = db.query_spo2(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["avg"] == 96.5

    def test_hrv_save_query(self, tmp_db):
        db.save_hrv(tmp_db, {"date": "2026-03-15", "daily_rmssd": 38.5, "deep_rmssd": 45.0})
        tmp_db.commit()
        rows = db.query_hrv(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["daily_rmssd"] == 38.5


class TestUpsert:
    """Test that INSERT OR REPLACE works correctly."""

    def test_heart_rate_upsert(self, tmp_db):
        db.save_heart_rate(tmp_db, "2026-03-15", 60, [])
        db.save_heart_rate(tmp_db, "2026-03-15", 65, [])
        tmp_db.commit()
        rows = db.query_heart_rate(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["resting_hr"] == 65

    def test_activity_upsert(self, tmp_db):
        db.save_activity(tmp_db, {
            "date": "2026-03-15", "steps": 5000, "calories_out": 2000,
            "active_minutes": 20, "very_active_minutes": 10,
            "fairly_active_minutes": 10, "lightly_active_minutes": 150,
            "sedentary_minutes": 700, "floors": 3, "distance_km": 3.5,
        })
        db.save_activity(tmp_db, {
            "date": "2026-03-15", "steps": 12000, "calories_out": 2800,
            "active_minutes": 60, "very_active_minutes": 30,
            "fairly_active_minutes": 30, "lightly_active_minutes": 200,
            "sedentary_minutes": 400, "floors": 12, "distance_km": 9.0,
        })
        tmp_db.commit()
        rows = db.query_activity(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["steps"] == 12000

    def test_exercise_upsert_same_log_id(self, tmp_db):
        db.save_exercise(tmp_db, "log1", {
            "date": "2026-03-15", "name": "Walk", "duration_min": 30,
            "calories": 150, "avg_hr": 100, "steps": 3000,
            "distance_km": 2.0, "distance_unit": "Kilometer",
            "start_time": "2026-03-15T08:00:00", "source": "Tracker", "log_type": "auto_detected",
        })
        db.save_exercise(tmp_db, "log1", {
            "date": "2026-03-15", "name": "Walk", "duration_min": 45,
            "calories": 200, "avg_hr": 105, "steps": 4500,
            "distance_km": 3.0, "distance_unit": "Kilometer",
            "start_time": "2026-03-15T08:00:00", "source": "Tracker", "log_type": "auto_detected",
        })
        tmp_db.commit()
        rows = db.query_exercises(tmp_db, "2026-03-15", "2026-03-15")
        assert len(rows) == 1
        assert rows[0]["duration_min"] == 45


class TestDateRanges:
    """Test date range filtering in queries."""

    def test_query_returns_only_in_range(self, populated_db):
        rows = db.query_activity(populated_db, "2026-03-11", "2026-03-13")
        dates = [r["date"] for r in rows]
        assert "2026-03-10" not in dates
        assert "2026-03-11" in dates
        assert "2026-03-13" in dates
        assert "2026-03-14" not in dates

    def test_query_empty_range(self, populated_db):
        rows = db.query_activity(populated_db, "2025-01-01", "2025-01-31")
        assert rows == []

    def test_query_single_day(self, populated_db):
        rows = db.query_sleep(populated_db, "2026-03-12", "2026-03-12")
        assert len(rows) == 1


class TestSyncLog:
    """Test sync logging and last-synced-date lookups."""

    def test_log_sync(self, tmp_db):
        db.log_sync(tmp_db, "heart_rate", "ok", 10, "test")
        rows = tmp_db.execute("SELECT * FROM sync_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["data_type"] == "heart_rate"
        assert rows[0]["records_added"] == 10

    def test_get_last_synced_date(self, populated_db):
        last = db.get_last_synced_date(populated_db, "activity")
        assert last == "2026-03-14"

    def test_get_last_synced_date_empty_table(self, tmp_db):
        last = db.get_last_synced_date(tmp_db, "activity")
        assert last is None

    def test_get_last_synced_date_unknown_type(self, tmp_db):
        last = db.get_last_synced_date(tmp_db, "unknown_type")
        assert last is None
