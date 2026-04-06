"""Tests for MCP tool functions (the async wrappers)."""

import json
from unittest.mock import patch, MagicMock

import pytest

from fitbit_mcp.helpers import require_auth


class TestRequireAuth:
    """Test the auth decorator."""

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_missing_config(self, mock_tokens_path, mock_config_path):
        mock_config_path.exists.return_value = False
        mock_tokens_path.exists.return_value = True

        @require_auth
        async def tool_fn():
            return "should not reach"

        result = await tool_fn()
        parsed = json.loads(result)
        assert "error" in parsed
        assert "not configured" in parsed["error"]

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_missing_tokens(self, mock_tokens_path, mock_config_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = False

        @require_auth
        async def tool_fn():
            return "should not reach"

        result = await tool_fn()
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_auth_present_passes_through(self, mock_tokens_path, mock_config_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        @require_auth
        async def tool_fn():
            return "success"

        result = await tool_fn()
        assert result == "success"

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_preserves_function_name(self, mock_tokens_path, mock_config_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        @require_auth
        async def my_tool():
            return "ok"

        assert my_tool.__name__ == "my_tool"


class TestToolQueryFunctions:
    """Test tool query functions return correct structure from cache."""

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_activity_empty_cache(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.activity_tools import fitbit_get_activity
            result = await fitbit_get_activity(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "message" in parsed
        assert "No activity data" in parsed["message"]

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_activity_with_data(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"
        conn = db_mod.get_db(db_path)
        db_mod.save_activity(conn, {
            "date": "2026-03-12", "steps": 10000, "calories_out": 2500,
            "active_minutes": 45, "very_active_minutes": 20,
            "fairly_active_minutes": 25, "lightly_active_minutes": 200,
            "sedentary_minutes": 500, "floors": 10, "distance_km": 7.5,
        })
        conn.commit()
        conn.close()

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.activity_tools import fitbit_get_activity
            result = await fitbit_get_activity(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "activity" in parsed
        assert parsed["count"] == 1
        assert parsed["activity"][0]["steps"] == 10000

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_sleep_empty_cache(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.sleep_tools import fitbit_get_sleep
            result = await fitbit_get_sleep(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "No sleep data" in parsed["message"]

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_heart_rate_empty_cache(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.heart_tools import fitbit_get_heart_rate
            result = await fitbit_get_heart_rate(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "No heart rate data" in parsed["message"]

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_trends_empty_cache(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.analysis_tools import fitbit_trends
            result = await fitbit_trends(
                data_type="activity",
                start_date="2026-03-01",
                end_date="2026-03-31",
            )

        parsed = json.loads(result)
        assert "message" in parsed

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_trends_invalid_type(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.analysis_tools import fitbit_trends
            result = await fitbit_trends(data_type="nonexistent")

        parsed = json.loads(result)
        assert "error" in parsed

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_exercises_empty_cache(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.exercise_tools import fitbit_get_exercises
            result = await fitbit_get_exercises(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "No exercise entries" in parsed["message"]

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_exercises_with_data(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"
        conn = db_mod.get_db(db_path)
        db_mod.save_exercise(conn, "log001", {
            "date": "2026-03-12", "name": "Cycling", "duration_min": 45,
            "calories": 350, "avg_hr": 130, "steps": None,
            "distance_km": 12.0, "distance_unit": "Kilometer",
            "start_time": "2026-03-12T07:30:00", "source": "Tracker", "log_type": "auto_detected",
        })
        conn.commit()
        conn.close()

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.exercise_tools import fitbit_get_exercises
            result = await fitbit_get_exercises(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "exercises" in parsed
        assert parsed["count"] == 1
        assert parsed["exercises"][0]["name"] == "Cycling"

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_exercises_type_filter(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"
        conn = db_mod.get_db(db_path)
        db_mod.save_exercise(conn, "log001", {
            "date": "2026-03-12", "name": "Cycling", "duration_min": 45,
            "calories": 350, "avg_hr": 130, "steps": None,
            "distance_km": 12.0, "distance_unit": "Kilometer",
            "start_time": "2026-03-12T07:30:00", "source": "Tracker", "log_type": "auto",
        })
        db_mod.save_exercise(conn, "log002", {
            "date": "2026-03-13", "name": "Walk", "duration_min": 30,
            "calories": 180, "avg_hr": 100, "steps": 4000,
            "distance_km": 2.5, "distance_unit": "Kilometer",
            "start_time": "2026-03-13T12:00:00", "source": "Tracker", "log_type": "auto",
        })
        conn.commit()
        conn.close()

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.exercise_tools import fitbit_get_exercises
            result = await fitbit_get_exercises(
                start_date="2026-03-10", end_date="2026-03-15", exercise_type="cycl"
            )

        parsed = json.loads(result)
        assert parsed["count"] == 1
        assert parsed["exercises"][0]["name"] == "Cycling"

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_weight_empty_cache(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.weight_tools import fitbit_get_weight
            result = await fitbit_get_weight(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "No weight data" in parsed["message"]

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_weight_with_data(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"
        conn = db_mod.get_db(db_path)
        db_mod.save_weight(conn, {"date": "2026-03-12", "weight_kg": 79.5, "bmi": 24.5, "fat_pct": 19.0})
        conn.commit()
        conn.close()

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.weight_tools import fitbit_get_weight
            result = await fitbit_get_weight(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "weight" in parsed
        assert parsed["count"] == 1
        assert parsed["weight"][0]["weight_kg"] == 79.5

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_spo2_empty_cache(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.spo2_tools import fitbit_get_spo2
            result = await fitbit_get_spo2(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "No SpO2 data" in parsed["message"]

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_spo2_with_data(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"
        conn = db_mod.get_db(db_path)
        db_mod.save_spo2(conn, {"date": "2026-03-12", "avg": 96.5, "min": 93.0, "max": 99.0})
        conn.commit()
        conn.close()

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.spo2_tools import fitbit_get_spo2
            result = await fitbit_get_spo2(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "spo2" in parsed
        assert parsed["count"] == 1
        assert parsed["spo2"][0]["avg"] == 96.5

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_hrv_empty_cache(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.hrv_tools import fitbit_get_hrv
            result = await fitbit_get_hrv(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "No HRV data" in parsed["message"]

    @patch("fitbit_mcp.helpers.FITBIT_CONFIG_PATH")
    @patch("fitbit_mcp.helpers.FITBIT_TOKENS_PATH")
    async def test_hrv_with_data(self, mock_tokens_path, mock_config_path, tmp_path):
        mock_config_path.exists.return_value = True
        mock_tokens_path.exists.return_value = True

        from fitbit_mcp import db as db_mod
        db_path = tmp_path / "test.db"
        conn = db_mod.get_db(db_path)
        db_mod.save_hrv(conn, {"date": "2026-03-12", "daily_rmssd": 38.0, "deep_rmssd": 44.0})
        conn.commit()
        conn.close()

        with patch.object(db_mod, "DB_PATH", db_path):
            from fitbit_mcp.tools.hrv_tools import fitbit_get_hrv
            result = await fitbit_get_hrv(start_date="2026-03-10", end_date="2026-03-15")

        parsed = json.loads(result)
        assert "hrv" in parsed
        assert parsed["count"] == 1
        assert parsed["hrv"][0]["daily_rmssd"] == 38.0
