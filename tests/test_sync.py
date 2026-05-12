"""Tests for the sync tool logic."""

from datetime import date, timedelta
from unittest.mock import patch

from fitbit_mcp import db
from fitbit_mcp.tools.sync_tools import (
    _chunk_date_ranges,
    _parse_vo2_max,
    _sync_activity,
    _sync_azm,
    _sync_breathing_rate,
    _sync_cardio_fitness,
    _sync_exercises,
    _sync_food_log,
    _sync_heart_rate,
    _sync_hrv,
    _sync_skin_temperature,
    _sync_sleep,
    _sync_spo2,
    _sync_weight,
    run_sync,
)


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
            assert ranges[i][0] == ranges[i - 1][1] + timedelta(days=1)

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
                "steps": 9500,
                "caloriesOut": 2300,
                "veryActiveMinutes": 25,
                "fairlyActiveMinutes": 10,
                "lightlyActiveMinutes": 180,
                "sedentaryMinutes": 580,
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
                    "levels": {
                        "summary": {
                            "deep": {"minutes": 60},
                            "light": {"minutes": 200},
                            "rem": {"minutes": 100},
                            "wake": {"minutes": 60},
                        }
                    },
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


class TestSyncAzm:
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "activities-active-zone-minutes": [
                {
                    "dateTime": "2026-03-15",
                    "value": {
                        "activeZoneMinutes": 42,
                        "fatBurnActiveZoneMinutes": 25,
                        "cardioActiveZoneMinutes": 12,
                        "peakActiveZoneMinutes": 5,
                    },
                },
            ]
        }
        count = _sync_azm(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1
        rows = db.query_azm(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["total_minutes"] == 42
        assert rows[0]["peak_minutes"] == 5

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_correct_url(self, mock_get, tmp_db):
        mock_get.return_value = {"activities-active-zone-minutes": []}
        _sync_azm(tmp_db, date(2026, 3, 1), date(2026, 3, 5))
        url = mock_get.call_args[0][0]
        assert "/activities/active-zone-minutes/date/2026-03-01/2026-03-05.json" in url


class TestSyncBreathingRate:
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "br": [
                {"dateTime": "2026-03-15", "value": {"breathingRate": 14.2}},
            ]
        }
        count = _sync_breathing_rate(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1
        rows = db.query_breathing_rate(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["breaths_per_min"] == 14.2

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_skips_missing_value(self, mock_get, tmp_db):
        mock_get.return_value = {"br": [{"dateTime": "2026-03-15", "value": {}}]}
        count = _sync_breathing_rate(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 0


class TestSyncSkinTemperature:
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "tempSkin": [
                {"dateTime": "2026-03-15", "value": {"nightlyRelative": -0.3}, "logType": "dermal"},
            ]
        }
        count = _sync_skin_temperature(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1
        rows = db.query_skin_temperature(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["nightly_relative"] == -0.3
        assert rows[0]["log_type"] == "dermal"


class TestParseVo2Max:
    def test_numeric(self):
        assert _parse_vo2_max(40) == (40.0, 40.0)
        assert _parse_vo2_max(40.5) == (40.5, 40.5)

    def test_range_string(self):
        assert _parse_vo2_max("39-43") == (39.0, 43.0)

    def test_single_value_string(self):
        assert _parse_vo2_max("40") == (40.0, 40.0)

    def test_invalid(self):
        assert _parse_vo2_max(None) == (None, None)
        assert _parse_vo2_max("abc") == (None, None)


class TestSyncCardioFitness:
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "cardioScore": [
                {"dateTime": "2026-03-15", "value": {"vo2Max": "39-43"}},
            ]
        }
        count = _sync_cardio_fitness(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1
        rows = db.query_cardio_fitness(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["vo2_max_low"] == 39.0
        assert rows[0]["vo2_max_high"] == 43.0

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_skips_unparseable(self, mock_get, tmp_db):
        mock_get.return_value = {
            "cardioScore": [{"dateTime": "2026-03-15", "value": {"vo2Max": "??"}}]
        }
        count = _sync_cardio_fitness(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 0


class TestSyncFoodLog:
    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_basic_sync(self, mock_get, tmp_db):
        mock_get.return_value = {
            "foods": [{"logId": 1}],
            "summary": {"calories": 2100, "water": 1800},
        }
        count = _sync_food_log(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1
        rows = db.query_food_log(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["calories_in"] == 2100
        assert rows[0]["water_ml"] == 1800

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_skips_empty_summary(self, mock_get, tmp_db):
        mock_get.return_value = {"summary": {}}
        count = _sync_food_log(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 0

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_skips_zero_summary_no_foods(self, mock_get, tmp_db):
        """Fitbit returns calories=0, water=0 for unlogged days - must not save."""
        mock_get.return_value = {"foods": [], "summary": {"calories": 0, "water": 0}}
        count = _sync_food_log(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 0
        rows = db.query_food_log(tmp_db, "2026-03-15", "2026-03-15")
        assert rows == []

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_water_only_is_saved(self, mock_get, tmp_db):
        mock_get.return_value = {"foods": [], "summary": {"calories": 0, "water": 500}}
        count = _sync_food_log(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1
        rows = db.query_food_log(tmp_db, "2026-03-15", "2026-03-15")
        assert rows[0]["water_ml"] == 500

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    def test_food_logged_with_zero_summary_calories_is_saved(self, mock_get, tmp_db):
        """If there are food entries but summary calories happen to be 0, still save."""
        mock_get.return_value = {
            "foods": [{"logId": 99, "name": "Water"}],
            "summary": {"calories": 0, "water": 0},
        }
        count = _sync_food_log(tmp_db, date(2026, 3, 15), date(2026, 3, 15))
        assert count == 1


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

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    @patch("fitbit_mcp.tools.sync_tools.db.get_db")
    def test_records_last_date_attempted(self, mock_get_db, mock_api_get, tmp_path):
        """Successful sync stores its end-date in sync_log.last_date_attempted."""
        from fitbit_mcp import db as db_mod

        db_path = tmp_path / "test.db"
        # Note: db.get_db is patched, so we can't call it through db_mod here.
        # Use sqlite3 directly to seed a real DB, then have the patched get_db
        # return that conn for run_sync; reopen afterwards to query.
        import sqlite3

        # First call: build a real DB by bypassing the patch
        from fitbit_mcp.db import SCHEMA, _migrate

        seed = sqlite3.connect(str(db_path))
        seed.row_factory = sqlite3.Row
        seed.executescript(SCHEMA)
        _migrate(seed)
        mock_get_db.return_value = seed
        mock_api_get.return_value = {"activities-heart": []}

        run_sync(["heart_rate"], days=7)

        # Reopen for verification (run_sync closes the conn)
        verify = sqlite3.connect(str(db_path))
        verify.row_factory = sqlite3.Row
        last = db_mod.get_last_attempted_date(verify, "heart_rate")
        verify.close()
        assert last == date.today().isoformat()

    @patch("fitbit_mcp.tools.sync_tools.api.get")
    @patch("fitbit_mcp.tools.sync_tools.db.get_db")
    def test_uses_attempted_date_to_skip_empty_days(self, mock_get_db, mock_api_get, tmp_db):
        """For sparse types, sync starts from last attempted date, not last data row."""
        from fitbit_mcp import db as db_mod

        mock_get_db.return_value = tmp_db

        # Simulate yesterday's run: data table has one old row, sync_log
        # records that we attempted up to yesterday and found no new logs.
        db_mod.save_food_log(tmp_db, {"date": "2026-01-01", "calories_in": 1800, "water_ml": 1000})
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        db_mod.log_sync(tmp_db, "food_log", "ok", 0, last_date_attempted=yesterday)
        tmp_db.commit()

        # Today's run should start from yesterday, not from 2026-01-01.
        mock_api_get.return_value = {"foods": [], "summary": {"calories": 0, "water": 0}}
        run_sync(["food_log"])

        call_paths = [c[0][0] for c in mock_api_get.call_args_list]
        assert any(yesterday in p for p in call_paths)
        assert not any("2026-01-01" in p for p in call_paths)
