"""Tests for JSON data importer."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from fitbit_mcp import db


class TestImporter:
    """Test bulk JSON import."""

    def _write_json(self, path: Path, data: dict):
        path.write_text(json.dumps(data))

    def _run_import(self, data_dir, db_path):
        """Run import with db.get_db patched to use our test database."""
        with patch("fitbit_mcp.db.DB_PATH", db_path):
            from fitbit_mcp.importer import run_import
            run_import(data_dir)

    def test_import_heart_rate(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        self._write_json(data_dir / "heart_rate.json", {
            "2026-03-10": {"resting_hr": 62, "heart_rate_zones": [{"name": "Fat Burn", "minutes": 30}]},
            "2026-03-11": {"resting_hr": 64, "heart_rate_zones": []},
            "_metadata": {"ignore": True},
        })

        db_path = tmp_path / "test.db"
        self._run_import(data_dir, db_path)

        conn = db.get_db(db_path)
        rows = db.query_heart_rate(conn, "2026-03-10", "2026-03-11")
        assert len(rows) == 2
        assert rows[0]["resting_hr"] == 62
        conn.close()

    def test_import_activity(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        self._write_json(data_dir / "activity.json", {
            "2026-03-10": {
                "steps": 8500, "calories_out": 2300, "active_minutes": 35,
                "very_active_minutes": 15, "fairly_active_minutes": 20,
                "lightly_active_minutes": 180, "sedentary_minutes": 600,
                "floors": 7, "distance_km": 6.2,
            },
        })

        db_path = tmp_path / "test.db"
        self._run_import(data_dir, db_path)

        conn = db.get_db(db_path)
        rows = db.query_activity(conn, "2026-03-10", "2026-03-10")
        assert len(rows) == 1
        assert rows[0]["steps"] == 8500
        conn.close()

    def test_import_sleep(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        self._write_json(data_dir / "sleep.json", {
            "2026-03-10": {
                "total_minutes": 420, "efficiency": 91,
                "start_time": "2026-03-09T23:00:00", "end_time": "2026-03-10T06:00:00",
                "deep_minutes": 65, "light_minutes": 200,
                "rem_minutes": 100, "wake_minutes": 55,
            },
        })

        db_path = tmp_path / "test.db"
        self._run_import(data_dir, db_path)

        conn = db.get_db(db_path)
        rows = db.query_sleep(conn, "2026-03-10", "2026-03-10")
        assert len(rows) == 1
        assert rows[0]["total_minutes"] == 420
        conn.close()

    def test_import_weight(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        self._write_json(data_dir / "weight.json", {
            "2026-03-10": {"weight_kg": 79.0, "bmi": 24.5, "fat_pct": 19.0},
        })

        db_path = tmp_path / "test.db"
        self._run_import(data_dir, db_path)

        conn = db.get_db(db_path)
        rows = db.query_weight(conn, "2026-03-10", "2026-03-10")
        assert len(rows) == 1
        assert rows[0]["weight_kg"] == 79.0
        conn.close()

    def test_import_exercises(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        self._write_json(data_dir / "exercises.json", {
            "log001": {
                "date": "2026-03-10", "name": "Walk", "duration_min": 45,
                "calories": 200, "avg_hr": 105, "steps": 5000,
                "distance_km": 3.5, "distance_unit": "Kilometer",
                "start_time": "2026-03-10T08:00:00", "source": "Tracker",
                "log_type": "auto_detected",
            },
        })

        db_path = tmp_path / "test.db"
        self._run_import(data_dir, db_path)

        conn = db.get_db(db_path)
        rows = db.query_exercises(conn, "2026-03-10", "2026-03-10")
        assert len(rows) == 1
        assert rows[0]["name"] == "Walk"
        conn.close()

    def test_import_spo2(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        self._write_json(data_dir / "spo2.json", {
            "2026-03-10": {"avg": 96.5, "min": 93.0, "max": 99.0},
        })

        db_path = tmp_path / "test.db"
        self._run_import(data_dir, db_path)

        conn = db.get_db(db_path)
        rows = db.query_spo2(conn, "2026-03-10", "2026-03-10")
        assert len(rows) == 1
        assert rows[0]["avg"] == 96.5
        conn.close()

    def test_import_hrv(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        self._write_json(data_dir / "hrv.json", {
            "2026-03-10": {"daily_rmssd": 38.0, "deep_rmssd": 44.0},
        })

        db_path = tmp_path / "test.db"
        self._run_import(data_dir, db_path)

        conn = db.get_db(db_path)
        rows = db.query_hrv(conn, "2026-03-10", "2026-03-10")
        assert len(rows) == 1
        assert rows[0]["daily_rmssd"] == 38.0
        conn.close()

    def test_import_skips_metadata_keys(self, tmp_path):
        """Keys starting with '_' should be skipped."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        self._write_json(data_dir / "heart_rate.json", {
            "_fetched_at": "2026-03-15T10:00:00",
            "_source": "fitbit-api",
            "2026-03-10": {"resting_hr": 62, "heart_rate_zones": []},
        })

        db_path = tmp_path / "test.db"
        self._run_import(data_dir, db_path)

        conn = db.get_db(db_path)
        rows = db.query_heart_rate(conn, "2026-01-01", "2026-12-31")
        assert len(rows) == 1
        conn.close()

    def test_import_missing_files_skipped(self, tmp_path):
        """Import should succeed even if some JSON files are missing."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Only create one file
        self._write_json(data_dir / "weight.json", {
            "2026-03-10": {"weight_kg": 79.0, "bmi": 24.5, "fat_pct": 19.0},
        })

        db_path = tmp_path / "test.db"
        self._run_import(data_dir, db_path)

        conn = db.get_db(db_path)
        assert len(db.query_weight(conn, "2026-03-10", "2026-03-10")) == 1
        assert len(db.query_heart_rate(conn, "2026-01-01", "2026-12-31")) == 0
        conn.close()

    def test_import_nonexistent_dir_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            from fitbit_mcp.importer import run_import
            run_import(tmp_path / "nonexistent")
