"""Tests for the sync tool logic."""

import json
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import pytest

from fitbit_mcp.tools.sync_tools import (
    _chunk_date_ranges,
    _sync_heart_rate,
    _sync_activity,
    _sync_sleep,
    _sync_weight,
    _sync_spo2,
    _sync_hrv,
    _sync_exercises,
    run_sync,
)
from fitbit_mcp import db


class TestChunkDateRanges:
    """Test date range splitting."""

    def test_single_chunk(self):
        ranges = _chunk_date_ranges(date(2026, 3, 1), date(2026, 3, 10), max_days=30)
        assert len(ranges) == 1
        assert ranges[0] == (date(2026, 3, 1), date(2026, 3, 10))

    def test_exact_chunk_size(self):
        ranges = _chunk_date_ranges(date(2026, 3, 1), date(2026, 3, 30), max_days=30)
        assert len(ranges) == 1

    def test_two_chunks(self):
        ranges = _chunk_date_ranges(date(2026, 3, 1), date(2026, 3, 31), max_days=20)
        assert len(ranges) == 2
        assert ranges[0] == (date(2026, 3, 1), date(2026, 3, 20))
        assert ranges[1] == (date(2026, 3, 21), date(2026, 3, 31))

    def test_many_chunks(self):
        ranges = _chunk_date_ranges(date(2026, 1, 1), date(2026, 12, 31), max_days=30)
        assert len(ranges) >= 12
        # Check no gaps
        for i in range(1, len(ranges)):
            assert ranges[i][0] == ranges[i-1][1] + timedelta(days=1)

    def test_single_day(self):
        ranges = _chunk_date_ranges(date(2026, 3, 15), date(2026, 3, 15), max_days=30)
        assert len(ranges) == 1
        assert ranges[0] == (date(2026, 3, 15), date(2026, 3, 15))


class TestSyncHeartRate:
    """Test heart rate sync from API to DB."""

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "activities-heart": [
                {
                    "dateTime": "2026-03-15",
                    "value": {
                        "restingHeartRate": 62,
                        "heartRateZones": [{"name": "Fat Burn", "minutes": 30}],
                    },
                },
                {
                    "dateTime": "2026-03-16",
                    "value": {
                        "restingHeartRate": 65,
                        "heartRateZones": [],
                    },
                },
            ]
        }

        count = _sync_heart_rate(tmp_db, date(2026, 3, 15), date(2026, 3, 16))
        assert count == 2

        rows = db.query_heart_rate(tmp_db, "2026-03-15", "2026-03-16")
        assert len(rows) == 2
        assert rows[0]["resting_hr"] == 62

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_empty_response(self, mock_get, tmp_db):
        mock_get.return_value = {"activities-heart": []}
        count = _sync_heart_rate(tmp_db, date(2026, 3, 15), date(2026, 3, 16))
        assert count == 0


class TestSyncActivity:
    """Test daily activity sync from API to DB."""

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "summary": {
                "steps": 9500, "caloriesOut": 2300,
                "veryActiveMinutes": 25, "fairlyActiveMinutes": 10,
                "lightlyActiveMinutes": 180, "sedentaryMinutes": 580,
                "floors": 6,
                "distances": [{"distance": 6.8}],
            }
        }

        count = _sync_activity(tmp_db, date(2026, 3, 15), date(2026, 3, 16))
        assert count == 2  # one per day
        assert mock_get.call_count == 2

        rows = db.query_activity(tmp_db, "2026-03-15", "2026-03-16")
        assert len(rows) == 2
        assert rows[0]["steps"] == 9500
        assert rows[0]["active_minutes"] == 35  # 25 + 10
        assert rows[0]["distance_km"] == 6.8

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_correct_api_url_per_day(self, mock_get, tmp_db):
        mock_get.return_value = {"summary": {}}
        _sync_activity(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        url = mock_get.call_args[0][0]
        assert "/activities/date/2026-03-15.json" in url

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_empty_summary(self, mock_get, tmp_db):
        mock_get.return_value = {"summary": {}}
        count = _sync_activity(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1
        rows = db.query_activity(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["steps"] is None

    @patch("fitbit_mcp.tools.sync_tools.time.sleep")
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_rate_limit_retry(self, mock_get, mock_sleep, tmp_db):
        """On 429, sync sleeps then retries the same day."""
        from fitbit_mcp.api import FitbitRateLimitError
        ok_response = {"summary": {"steps": 8000, "distances": [{"distance": 5.0}]}}
        mock_get.side_effect = [FitbitRateLimitError(60), ok_response]

        count = _sync_activity(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1
        mock_sleep.assert_called_once_with(65)  # reset_seconds + 5


class TestSyncSleep:
    """Test sleep sync from API to DB."""

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "sleep": [
                {
                    "dateOfSleep": "2026-03-15",
                    "minutesAsleep": 420,
                    "efficiency": 91,
                    "startTime": "2026-03-14T23:00:00",
                    "endTime": "2026-03-15T06:00:00",
                    "levels": {"summary": {
                        "deep": {"minutes": 60},
                        "light": {"minutes": 200},
                        "rem": {"minutes": 100},
                        "wake": {"minutes": 60},
                    }},
                },
            ]
        }

        count = _sync_sleep(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1

        rows = db.query_sleep(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["deep_minutes"] == 60

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_skips_no_date(self, mock_get, tmp_db):
        mock_get.return_value = {
            "sleep": [{"minutesAsleep": 420}]  # no dateOfSleep
        }
        count = _sync_sleep(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 0


class TestSyncWeight:
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "weight": [
                {"date": "2026-03-15", "weight": 78.5, "bmi": 24.2, "fat": 18.5},
            ]
        }

        count = _sync_weight(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1

        rows = db.query_weight(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["weight_kg"] == 78.5


class TestSyncSpO2:
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_list_response(self, mock_get, tmp_db):
        """SpO2 API can return a list instead of a dict."""
        mock_get.return_value = [
            {"dateTime": "2026-03-15", "value": {"avg": 96.5, "min": 93.0, "max": 99.0}},
        ]

        count = _sync_spo2(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_dict_response(self, mock_get, tmp_db):
        """SpO2 API can also return a single dict."""
        mock_get.return_value = {
            "dateTime": "2026-03-15",
            "value": {"avg": 96.5, "min": 93.0, "max": 99.0},
        }

        count = _sync_spo2(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1


class TestSyncHRV:
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "hrv": [
                {"dateTime": "2026-03-15", "value": {"dailyRmssd": 38.0, "deepRmssd": 44.0}},
            ]
        }

        count = _sync_hrv(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1

        rows = db.query_hrv(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["daily_rmssd"] == 38.0


class TestSyncExercises:
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.side_effect = [
            {
                "activities": [
                    {
                        "logId": 12345,
                        "startTime": "2026-03-15T07:30:00",
                        "activityName": "Walk",
                        "activeDuration": 2700000,  # 45 min in ms
                        "calories": 200,
                        "averageHeartRate": 105,
                        "steps": 5000,
                        "distance": 3.5,
                        "distanceUnit": "Kilometer",
                        "source": {"name": "Tracker"},
                        "logType": "auto_detected",
                    },
                ]
            },
            {"activities": []},  # Pagination stop
        ]

        count = _sync_exercises(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1

        rows = db.query_exercises(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["name"] == "Walk"
        assert rows[0]["duration_min"] == 45


class TestRunSync:
    """Test the main sync orchestrator."""

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    @patch("fitbit_mcp.tools.sync_tools.db.get_db")
    def test_successful_sync(self, mock_get_db, mock_api_get, tmp_db):
        """run_sync calls the right sync fn, logs the result, and returns ok status."""
        mock_get_db.return_value = tmp_db
        mock_api_get.return_value = {
            "activities-heart": [
                {"dateTime": "2026-03-15", "value": {"restingHeartRate": 62, "heartRateZones": []}},
            ]
        }

        results = run_sync(["heart_rate"], days=7)
        assert results["heart_rate"]["status"] == "ok"
        assert results["heart_rate"]["records"] == 1
        assert "range" in results["heart_rate"]

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    @patch("fitbit_mcp.tools.sync_tools.db.get_db")
    def test_unknown_type(self, mock_get_db, mock_api_get, tmp_db):
        mock_get_db.return_value = tmp_db
        results = run_sync(["invalid_type"], days=7)
        assert results["invalid_type"]["status"] == "error"

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    @patch("fitbit_mcp.tools.sync_tools.db.get_db")
    def test_auth_error_handled(self, mock_get_db, mock_api_get, tmp_db):
        from fitbit_mcp.api import FitbitAuthError
        mock_get_db.return_value = tmp_db
        mock_api_get.side_effect = FitbitAuthError("expired")

        results = run_sync(["heart_rate"], days=7)
        assert results["heart_rate"]["status"] == "auth_error"

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    @patch("fitbit_mcp.tools.sync_tools.db.get_db")
    def test_rate_limit_handled(self, mock_get_db, mock_api_get, tmp_db):
        from fitbit_mcp.api import FitbitRateLimitError
        mock_get_db.return_value = tmp_db
        mock_api_get.side_effect = FitbitRateLimitError(300)

        results = run_sync(["heart_rate"], days=7)
        assert results["heart_rate"]["status"] == "rate_limited"
