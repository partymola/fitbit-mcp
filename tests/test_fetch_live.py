"""Tests for the _fetch_live() functions in each query tool.

These functions hit the Fitbit API directly and are distinct from the cache
query path. Each test patches api.get and verifies correct URL construction,
response parsing, and deduplication logic.
"""

from datetime import date
from unittest.mock import call, patch

import pytest

from fitbit_mcp.tools.heart_tools import _fetch_live as heart_fetch_live
from fitbit_mcp.tools.activity_tools import _fetch_live as activity_fetch_live
from fitbit_mcp.tools.sleep_tools import _fetch_live as sleep_fetch_live
from fitbit_mcp.tools.exercise_tools import _fetch_live as exercise_fetch_live
from fitbit_mcp.tools.weight_tools import _fetch_live as weight_fetch_live
from fitbit_mcp.tools.spo2_tools import _fetch_live as spo2_fetch_live
from fitbit_mcp.tools.hrv_tools import _fetch_live as hrv_fetch_live
from fitbit_mcp.tools.azm_tools import _fetch_live as azm_fetch_live
from fitbit_mcp.tools.breathing_rate_tools import _fetch_live as breathing_rate_fetch_live
from fitbit_mcp.tools.temperature_tools import _fetch_live as temperature_fetch_live
from fitbit_mcp.tools.cardio_fitness_tools import _fetch_live as cardio_fitness_fetch_live
from fitbit_mcp.tools.food_tools import _fetch_live as food_fetch_live
from fitbit_mcp.tools.devices_tools import _fetch_devices
from fitbit_mcp.tools.lifetime_stats_tools import _fetch_lifetime, _fetch_goals


class TestHeartFetchLive:
    @patch("fitbit_mcp.tools.heart_tools.api.get")
    def test_returns_entries(self, mock_get):
        mock_get.return_value = {
            "activities-heart": [
                {"dateTime": "2026-03-15", "value": {"restingHeartRate": 62, "heartRateZones": []}},
                {"dateTime": "2026-03-16", "value": {"restingHeartRate": 64, "heartRateZones": []}},
            ]
        }
        result = heart_fetch_live(date(2026, 3, 15), date(2026, 3, 16))
        assert len(result) == 2
        assert result[0]["date"] == "2026-03-15"
        assert result[0]["resting_hr"] == 62
        assert result[1]["resting_hr"] == 64

    @patch("fitbit_mcp.tools.heart_tools.api.get")
    def test_correct_api_url(self, mock_get):
        mock_get.return_value = {"activities-heart": []}
        heart_fetch_live(date(2026, 3, 1), date(2026, 3, 31))
        url = mock_get.call_args[0][0]
        assert "/activities/heart/date/2026-03-01/2026-03-31.json" in url

    @patch("fitbit_mcp.tools.heart_tools.api.get")
    def test_chunked_large_range(self, mock_get):
        mock_get.return_value = {"activities-heart": []}
        # 400 days exceeds MAX_RANGE_DAYS=365, should make 2 API calls
        heart_fetch_live(date(2025, 1, 1), date(2026, 2, 4))
        assert mock_get.call_count == 2

    @patch("fitbit_mcp.tools.heart_tools.api.get")
    def test_missing_resting_hr_is_none(self, mock_get):
        mock_get.return_value = {
            "activities-heart": [
                {"dateTime": "2026-03-15", "value": {"heartRateZones": []}},
            ]
        }
        result = heart_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert result[0]["resting_hr"] is None


class TestActivityFetchLive:
    @patch("fitbit_mcp.tools.activity_tools.api.get")
    def test_returns_one_entry_per_day(self, mock_get):
        mock_get.return_value = {
            "summary": {
                "steps": 9000, "caloriesOut": 2400,
                "veryActiveMinutes": 20, "fairlyActiveMinutes": 15,
                "lightlyActiveMinutes": 180, "sedentaryMinutes": 600,
                "floors": 8,
                "distances": [{"activity": "total", "distance": 6.5}],
            }
        }
        result = activity_fetch_live(date(2026, 3, 15), date(2026, 3, 17))
        assert len(result) == 3
        assert mock_get.call_count == 3  # one call per day

    @patch("fitbit_mcp.tools.activity_tools.api.get")
    def test_correct_api_url_per_day(self, mock_get):
        mock_get.return_value = {"summary": {}}
        activity_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        url = mock_get.call_args[0][0]
        assert "/activities/date/2026-03-15.json" in url

    @patch("fitbit_mcp.tools.activity_tools.api.get")
    def test_entry_fields(self, mock_get):
        mock_get.return_value = {
            "summary": {
                "steps": 10000, "caloriesOut": 2500,
                "veryActiveMinutes": 30, "fairlyActiveMinutes": 20,
                "lightlyActiveMinutes": 200, "sedentaryMinutes": 500,
                "floors": 10,
                "distances": [{"distance": 7.0}],
            }
        }
        result = activity_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        e = result[0]
        assert e["date"] == "2026-03-15"
        assert e["steps"] == 10000
        assert e["active_minutes"] == 50  # very + fairly
        assert e["distance_km"] == 7.0

    @patch("fitbit_mcp.tools.activity_tools.api.get")
    def test_empty_summary(self, mock_get):
        mock_get.return_value = {"summary": {}}
        result = activity_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["steps"] is None


class TestSleepFetchLive:
    @patch("fitbit_mcp.tools.sleep_tools.api.get")
    def test_returns_entries(self, mock_get):
        mock_get.return_value = {
            "sleep": [
                {
                    "dateOfSleep": "2026-03-15",
                    "minutesAsleep": 420,
                    "efficiency": 91,
                    "startTime": "2026-03-14T23:00:00",
                    "endTime": "2026-03-15T06:00:00",
                    "levels": {"summary": {
                        "deep": {"minutes": 80},
                        "light": {"minutes": 200},
                        "rem": {"minutes": 100},
                        "wake": {"minutes": 40},
                    }},
                }
            ]
        }
        result = sleep_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["date"] == "2026-03-15"
        assert result[0]["total_minutes"] == 420
        assert result[0]["deep_minutes"] == 80

    @patch("fitbit_mcp.tools.sleep_tools.api.get")
    def test_deduplicates_keeps_longest(self, mock_get):
        """When two sleep entries share a date, the longer one is kept."""
        mock_get.return_value = {
            "sleep": [
                {
                    "dateOfSleep": "2026-03-15", "minutesAsleep": 300,
                    "efficiency": 85, "startTime": "2026-03-15T01:00:00",
                    "endTime": "2026-03-15T06:00:00",
                    "levels": {"summary": {}},
                },
                {
                    "dateOfSleep": "2026-03-15", "minutesAsleep": 420,
                    "efficiency": 91, "startTime": "2026-03-14T23:00:00",
                    "endTime": "2026-03-15T06:00:00",
                    "levels": {"summary": {}},
                },
            ]
        }
        result = sleep_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["total_minutes"] == 420

    @patch("fitbit_mcp.tools.sleep_tools.api.get")
    def test_skips_entries_without_date(self, mock_get):
        mock_get.return_value = {
            "sleep": [{"minutesAsleep": 360}]  # no dateOfSleep
        }
        result = sleep_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert result == []

    @patch("fitbit_mcp.tools.sleep_tools.api.get")
    def test_correct_api_url(self, mock_get):
        mock_get.return_value = {"sleep": []}
        sleep_fetch_live(date(2026, 3, 1), date(2026, 3, 31))
        url = mock_get.call_args[0][0]
        assert "/1.2/user/-/sleep/date/2026-03-01/2026-03-31.json" in url


class TestExerciseFetchLive:
    @patch("fitbit_mcp.tools.exercise_tools.api.get")
    def test_returns_entries(self, mock_get):
        mock_get.side_effect = [
            {
                "activities": [
                    {
                        "logId": 1, "startTime": "2026-03-15T07:30:00",
                        "activityName": "Cycling", "activeDuration": 1800000,
                        "calories": 300, "averageHeartRate": 130,
                        "distance": 8.0, "source": {"name": "Tracker"},
                        "logType": "auto_detected",
                    },
                ]
            },
            {"activities": []},
        ]
        result = exercise_fetch_live(date(2026, 3, 15), date(2026, 3, 15), None)
        assert len(result) == 1
        assert result[0]["name"] == "Cycling"
        assert result[0]["duration_min"] == 30

    @patch("fitbit_mcp.tools.exercise_tools.api.get")
    def test_type_filter(self, mock_get):
        """exercise_type filter does case-insensitive substring match."""
        mock_get.side_effect = [
            {
                "activities": [
                    {"logId": 1, "startTime": "2026-03-15T07:00:00", "activityName": "Cycling",
                     "activeDuration": 1800000, "calories": 300, "source": None, "logType": "auto"},
                    {"logId": 2, "startTime": "2026-03-15T18:00:00", "activityName": "Walk",
                     "activeDuration": 2700000, "calories": 200, "source": None, "logType": "auto"},
                ]
            },
            {"activities": []},
        ]
        result = exercise_fetch_live(date(2026, 3, 15), date(2026, 3, 15), "cycl")
        assert len(result) == 1
        assert result[0]["name"] == "Cycling"

    @patch("fitbit_mcp.tools.exercise_tools.api.get")
    def test_stops_at_end_date(self, mock_get):
        """Entries past end_date are not returned and pagination stops."""
        mock_get.return_value = {
            "activities": [
                {"logId": 1, "startTime": "2026-04-01T07:00:00", "activityName": "Walk",
                 "activeDuration": 1800000, "calories": 200, "source": None, "logType": "auto"},
            ]
        }
        result = exercise_fetch_live(date(2026, 3, 1), date(2026, 3, 31), None)
        assert result == []
        assert mock_get.call_count == 1  # stopped immediately


class TestWeightFetchLive:
    @patch("fitbit_mcp.tools.weight_tools.api.get")
    def test_returns_entries(self, mock_get):
        mock_get.return_value = {
            "weight": [
                {"date": "2026-03-15", "weight": 79.5, "bmi": 24.5, "fat": 19.0},
            ]
        }
        result = weight_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["weight_kg"] == 79.5
        assert result[0]["bmi"] == 24.5

    @patch("fitbit_mcp.tools.weight_tools.api.get")
    def test_deduplicates_by_date(self, mock_get):
        """Two weigh-ins on the same day: last one wins (dict keyed by date)."""
        mock_get.return_value = {
            "weight": [
                {"date": "2026-03-15", "weight": 79.5, "bmi": 24.5, "fat": 19.0},
                {"date": "2026-03-15", "weight": 79.2, "bmi": 24.4, "fat": 18.8},
            ]
        }
        result = weight_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1

    @patch("fitbit_mcp.tools.weight_tools.api.get")
    def test_skips_entries_without_date(self, mock_get):
        mock_get.return_value = {"weight": [{"weight": 79.5}]}  # no date
        result = weight_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert result == []


class TestSpo2FetchLive:
    @patch("fitbit_mcp.tools.spo2_tools.api.get")
    def test_list_response(self, mock_get):
        mock_get.return_value = [
            {"dateTime": "2026-03-15", "value": {"avg": 96.5, "min": 93.0, "max": 99.0}},
        ]
        result = spo2_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["avg"] == 96.5

    @patch("fitbit_mcp.tools.spo2_tools.api.get")
    def test_dict_response(self, mock_get):
        mock_get.return_value = {
            "dateTime": "2026-03-15",
            "value": {"avg": 96.5, "min": 93.0, "max": 99.0},
        }
        result = spo2_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["date"] == "2026-03-15"

    @patch("fitbit_mcp.tools.spo2_tools.api.get")
    def test_empty_dict_response(self, mock_get):
        """API returning {} (no data for period) produces no entries."""
        mock_get.return_value = {}
        result = spo2_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert result == []

    @patch("fitbit_mcp.tools.spo2_tools.api.get")
    def test_deduplicates_by_date(self, mock_get):
        """Two entries for the same date: last one wins."""
        mock_get.return_value = [
            {"dateTime": "2026-03-15", "value": {"avg": 96.0, "min": 92.0, "max": 99.0}},
            {"dateTime": "2026-03-15", "value": {"avg": 97.0, "min": 94.0, "max": 99.5}},
        ]
        result = spo2_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1


class TestHrvFetchLive:
    @patch("fitbit_mcp.tools.hrv_tools.api.get")
    def test_returns_entries(self, mock_get):
        mock_get.return_value = {
            "hrv": [
                {"dateTime": "2026-03-15", "value": {"dailyRmssd": 38.0, "deepRmssd": 44.0}},
            ]
        }
        result = hrv_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["daily_rmssd"] == 38.0
        assert result[0]["deep_rmssd"] == 44.0

    @patch("fitbit_mcp.tools.hrv_tools.api.get")
    def test_correct_api_url(self, mock_get):
        mock_get.return_value = {"hrv": []}
        hrv_fetch_live(date(2026, 3, 1), date(2026, 3, 30))
        url = mock_get.call_args[0][0]
        assert "/hrv/date/2026-03-01/2026-03-30.json" in url

    @patch("fitbit_mcp.tools.hrv_tools.api.get")
    def test_skips_entries_without_value(self, mock_get):
        mock_get.return_value = {
            "hrv": [
                {"dateTime": "2026-03-15"},  # no "value" key
            ]
        }
        result = hrv_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert result == []

    @patch("fitbit_mcp.tools.hrv_tools.api.get")
    def test_deduplicates_by_date(self, mock_get):
        mock_get.return_value = {
            "hrv": [
                {"dateTime": "2026-03-15", "value": {"dailyRmssd": 38.0, "deepRmssd": 44.0}},
                {"dateTime": "2026-03-15", "value": {"dailyRmssd": 40.0, "deepRmssd": 46.0}},
            ]
        }
        result = hrv_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1


class TestAzmFetchLive:
    @patch("fitbit_mcp.tools.azm_tools.api.get")
    def test_returns_entries(self, mock_get):
        mock_get.return_value = {
            "activities-active-zone-minutes": [
                {"dateTime": "2026-03-15", "value": {
                    "activeZoneMinutes": 42, "fatBurnActiveZoneMinutes": 25,
                    "cardioActiveZoneMinutes": 12, "peakActiveZoneMinutes": 5,
                }},
            ]
        }
        result = azm_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["total_minutes"] == 42
        assert result[0]["peak_minutes"] == 5

    @patch("fitbit_mcp.tools.azm_tools.api.get")
    def test_correct_url(self, mock_get):
        mock_get.return_value = {"activities-active-zone-minutes": []}
        azm_fetch_live(date(2026, 3, 1), date(2026, 3, 5))
        url = mock_get.call_args[0][0]
        assert "/activities/active-zone-minutes/date/2026-03-01/2026-03-05.json" in url


class TestBreathingRateFetchLive:
    @patch("fitbit_mcp.tools.breathing_rate_tools.api.get")
    def test_returns_entries(self, mock_get):
        mock_get.return_value = {
            "br": [{"dateTime": "2026-03-15", "value": {"breathingRate": 14.5}}]
        }
        result = breathing_rate_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["breaths_per_min"] == 14.5

    @patch("fitbit_mcp.tools.breathing_rate_tools.api.get")
    def test_skips_missing(self, mock_get):
        mock_get.return_value = {"br": [{"dateTime": "2026-03-15", "value": {}}]}
        result = breathing_rate_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert result == []


class TestTemperatureFetchLive:
    @patch("fitbit_mcp.tools.temperature_tools.api.get")
    def test_returns_entries(self, mock_get):
        mock_get.return_value = {
            "tempSkin": [
                {"dateTime": "2026-03-15", "value": {"nightlyRelative": -0.4}, "logType": "dermal"},
            ]
        }
        result = temperature_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["nightly_relative"] == -0.4
        assert result[0]["log_type"] == "dermal"


class TestCardioFitnessFetchLive:
    @patch("fitbit_mcp.tools.cardio_fitness_tools.api.get")
    def test_returns_range(self, mock_get):
        mock_get.return_value = {
            "cardioScore": [{"dateTime": "2026-03-15", "value": {"vo2Max": "39-43"}}]
        }
        result = cardio_fitness_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert len(result) == 1
        assert result[0]["vo2_max_low"] == 39.0
        assert result[0]["vo2_max_high"] == 43.0

    @patch("fitbit_mcp.tools.cardio_fitness_tools.api.get")
    def test_returns_single_value(self, mock_get):
        mock_get.return_value = {
            "cardioScore": [{"dateTime": "2026-03-15", "value": {"vo2Max": 41}}]
        }
        result = cardio_fitness_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert result[0]["vo2_max_low"] == 41.0
        assert result[0]["vo2_max_high"] == 41.0


class TestFoodFetchLive:
    @patch("fitbit_mcp.tools.food_tools.api.get")
    def test_returns_entries(self, mock_get):
        mock_get.return_value = {
            "foods": [{"logId": 1}],
            "summary": {"calories": 2100, "water": 1800},
        }
        result = food_fetch_live(date(2026, 3, 15), date(2026, 3, 16))
        assert len(result) == 2
        assert result[0]["calories_in"] == 2100
        assert result[0]["water_ml"] == 1800

    @patch("fitbit_mcp.tools.food_tools.api.get")
    def test_skips_empty_days(self, mock_get):
        mock_get.return_value = {"summary": {}}
        result = food_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert result == []

    @patch("fitbit_mcp.tools.food_tools.api.get")
    def test_skips_zero_unlogged_days(self, mock_get):
        """Unlogged days return calories=0, water=0 - must not be returned."""
        mock_get.return_value = {"foods": [], "summary": {"calories": 0, "water": 0}}
        result = food_fetch_live(date(2026, 3, 15), date(2026, 3, 15))
        assert result == []


class TestDevicesFetch:
    @patch("fitbit_mcp.tools.devices_tools.api.get")
    def test_returns_devices(self, mock_get):
        mock_get.return_value = [
            {
                "id": "abc123", "type": "TRACKER", "deviceVersion": "Charge 6",
                "battery": "High", "batteryLevel": 88, "lastSyncTime": "2026-05-03T07:00:00",
                "mac": "AA:BB:CC:DD:EE:FF", "features": [],
            }
        ]
        result = _fetch_devices()
        assert len(result) == 1
        assert result[0]["device_version"] == "Charge 6"
        assert result[0]["battery_level"] == 88

    @patch("fitbit_mcp.tools.devices_tools.api.get")
    def test_handles_non_list(self, mock_get):
        mock_get.return_value = {}
        result = _fetch_devices()
        assert result == []


class TestLifetimeStatsFetch:
    @patch("fitbit_mcp.tools.lifetime_stats_tools.api.get")
    def test_returns_lifetime(self, mock_get):
        mock_get.return_value = {
            "lifetime": {
                "total": {"steps": 12345678, "distance": 9876.5, "floors": 1500, "caloriesOut": 0, "activeScore": -1},
                "tracker": {"steps": 12345678, "distance": 9876.5, "floors": 1500, "caloriesOut": 0, "activeScore": -1},
            },
            "best": {
                "total": {"steps": {"date": "2026-03-15", "value": 25000}},
                "tracker": {"steps": {"date": "2026-03-15", "value": 25000}},
            },
        }
        result = _fetch_lifetime()
        assert result["lifetime_total"]["steps"] == 12345678
        assert result["best_total"]["steps"]["value"] == 25000


class TestGoalsFetch:
    @patch("fitbit_mcp.tools.lifetime_stats_tools.api.get")
    def test_returns_goals(self, mock_get):
        mock_get.return_value = {
            "goals": {"steps": 10000, "distance": 8.0, "floors": 10, "caloriesOut": 2500, "activeMinutes": 30}
        }
        result = _fetch_goals("daily")
        assert result["steps"] == 10000
        assert result["activeMinutes"] == 30

    @patch("fitbit_mcp.tools.lifetime_stats_tools.api.get")
    def test_correct_url(self, mock_get):
        mock_get.return_value = {"goals": {}}
        _fetch_goals("weekly")
        url = mock_get.call_args[0][0]
        assert "/activities/goals/weekly.json" in url
