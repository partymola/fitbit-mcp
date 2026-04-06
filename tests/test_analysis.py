"""Tests for the trend analysis logic."""

import json
from datetime import date

import pytest

from fitbit_mcp.tools.analysis_tools import (
    _get_period_key,
    _avg,
    _trend_heart_rate,
    _trend_activity,
    _trend_exercises,
    _trend_sleep,
    _trend_weight,
    _trend_spo2,
    _trend_hrv,
    _compare_periods,
    _parse_compare_range,
)


class TestPeriodKey:
    """Test date-to-period bucketing."""

    def test_monthly(self):
        assert _get_period_key("2026-03-15", "monthly") == "2026-03"
        assert _get_period_key("2026-12-01", "monthly") == "2026-12"

    def test_weekly(self):
        key = _get_period_key("2026-03-15", "weekly")
        # 2026-03-15 is a Sunday, ISO week 11
        assert key.startswith("2026-W")

    def test_quarterly(self):
        assert _get_period_key("2026-01-15", "quarterly") == "2026-Q1"
        assert _get_period_key("2026-04-01", "quarterly") == "2026-Q2"
        assert _get_period_key("2026-07-31", "quarterly") == "2026-Q3"
        assert _get_period_key("2026-12-31", "quarterly") == "2026-Q4"


class TestAvg:
    """Test the averaging helper."""

    def test_normal(self):
        assert _avg([10, 20, 30]) == 20.0

    def test_empty(self):
        assert _avg([]) is None

    def test_single(self):
        assert _avg([42]) == 42.0

    def test_rounds_to_one_decimal(self):
        assert _avg([1, 2, 3]) == 2.0
        assert _avg([10, 11]) == 10.5


class TestTrendHeartRate:
    def test_basic(self, populated_db):
        result = _trend_heart_rate(populated_db, "2026-03-10", "2026-03-14", "monthly")
        assert "periods" in result
        assert result["data_type"] == "heart_rate"
        assert len(result["periods"]) == 1
        p = result["periods"][0]
        assert p["period"] == "2026-03"
        assert p["days"] == 5
        assert p["avg_resting_hr"] == 62.0  # avg of 60,61,62,63,64

    def test_empty(self, tmp_db):
        result = _trend_heart_rate(tmp_db, "2026-01-01", "2026-01-31", "monthly")
        assert "message" in result


class TestTrendActivity:
    def test_basic(self, populated_db):
        result = _trend_activity(populated_db, "2026-03-10", "2026-03-14", "monthly")
        assert result["data_type"] == "activity"
        p = result["periods"][0]
        assert p["days"] == 5
        # steps: 8000, 8500, 9000, 9500, 10000 -> avg 9000.0
        assert p["avg_steps"] == 9000.0
        # distances: 5.0, 5.5, 6.0, 6.5, 7.0 -> total 30.0
        assert p["total_distance_km"] == 30.0

    def test_empty(self, tmp_db):
        result = _trend_activity(tmp_db, "2026-01-01", "2026-01-31", "monthly")
        assert "message" in result


class TestTrendExercises:
    def test_basic(self, populated_db):
        result = _trend_exercises(populated_db, "2026-03-10", "2026-03-14", "monthly")
        assert result["data_type"] == "exercises"
        p = result["periods"][0]
        assert p["sessions"] == 3
        assert p["total_calories"] == 750  # 200 + 300 + 250

    def test_empty(self, tmp_db):
        result = _trend_exercises(tmp_db, "2026-01-01", "2026-01-31", "monthly")
        assert "message" in result


class TestTrendSleep:
    def test_basic(self, populated_db):
        result = _trend_sleep(populated_db, "2026-03-10", "2026-03-14", "monthly")
        assert result["data_type"] == "sleep"
        p = result["periods"][0]
        assert p["nights"] == 5
        assert "h" in p["avg_total_sleep"]  # formatted as Xh Ym

    def test_empty(self, tmp_db):
        result = _trend_sleep(tmp_db, "2026-01-01", "2026-01-31", "monthly")
        assert "message" in result


class TestTrendWeight:
    def test_basic(self, populated_db):
        result = _trend_weight(populated_db, "2026-03-10", "2026-03-16", "monthly")
        assert result["data_type"] == "weight"
        p = result["periods"][0]
        assert p["count"] == 3
        # weights: 80.0, 79.5, 79.0 -> avg 79.5
        assert p["avg_weight_kg"] == 79.5

    def test_empty(self, tmp_db):
        result = _trend_weight(tmp_db, "2026-01-01", "2026-01-31", "monthly")
        assert "message" in result


class TestTrendSpo2:
    def test_basic(self, populated_db):
        result = _trend_spo2(populated_db, "2026-03-10", "2026-03-14", "monthly")
        assert result["data_type"] == "spo2"
        p = result["periods"][0]
        assert p["nights"] == 5
        # avg: 96.0, 96.2, 96.4, 96.6, 96.8 -> avg 96.4
        assert p["avg_spo2"] == 96.4
        # min values: 93.0, 93.3, 93.6, 93.9, 94.2 -> min of mins = 93.0
        assert p["min_spo2"] == 93.0

    def test_empty(self, tmp_db):
        result = _trend_spo2(tmp_db, "2026-01-01", "2026-01-31", "monthly")
        assert "message" in result


class TestTrendHrv:
    def test_basic(self, populated_db):
        result = _trend_hrv(populated_db, "2026-03-10", "2026-03-14", "monthly")
        assert result["data_type"] == "hrv"
        p = result["periods"][0]
        assert p["nights"] == 5
        # daily_rmssd: 35.0, 37.0, 39.0, 41.0, 43.0 -> avg 39.0
        assert p["avg_daily_rmssd"] == 39.0
        # deep_rmssd: 40.0, 42.5, 45.0, 47.5, 50.0 -> avg 45.0
        assert p["avg_deep_rmssd"] == 45.0

    def test_empty(self, tmp_db):
        result = _trend_hrv(tmp_db, "2026-01-01", "2026-01-31", "monthly")
        assert "message" in result


class TestParseCompareRange:
    def test_last_nd(self):
        result = _parse_compare_range("last_30d")
        assert result is not None
        start, end = result
        assert end == date.today()
        assert (end - start).days == 30

    def test_previous_nd(self):
        result = _parse_compare_range("previous_30d")
        assert result is not None
        start, end = result
        assert (end - start).days == 30

    def test_month(self):
        result = _parse_compare_range("2026-03")
        assert result is not None
        start, end = result
        assert start == date(2026, 3, 1)
        assert end == date(2026, 3, 31)

    def test_quarter(self):
        result = _parse_compare_range("2026-Q1")
        assert result is not None
        start, end = result
        assert start == date(2026, 1, 1)
        assert end == date(2026, 3, 31)

    def test_quarter_q4(self):
        result = _parse_compare_range("2026-Q4")
        start, end = result
        assert start == date(2026, 10, 1)
        assert end == date(2026, 12, 31)

    def test_invalid(self):
        assert _parse_compare_range("garbage") is None
        assert _parse_compare_range("2026") is None


class TestComparePeriods:
    def test_valid_compare(self, populated_db):
        result = _compare_periods(populated_db, "activity", "2026-03 vs 2026-02")
        assert "period_1" in result
        assert "period_2" in result
        assert result["data_type"] == "activity"

    def test_invalid_format(self, populated_db):
        result = _compare_periods(populated_db, "activity", "just one period")
        assert "error" in result

    def test_invalid_data_type(self, populated_db):
        result = _compare_periods(populated_db, "invalid_type", "2026-03 vs 2026-02")
        assert "error" in result

    def test_compare_heart_rate(self, populated_db):
        result = _compare_periods(populated_db, "heart_rate", "2026-03 vs 2026-02")
        assert result["period_1"]["count"] > 0
        assert result["period_2"]["count"] == 0

    def test_compare_exercises(self, populated_db):
        result = _compare_periods(populated_db, "exercises", "2026-03 vs 2026-02")
        assert result["period_1"]["count"] == 3

    def test_compare_spo2(self, populated_db):
        result = _compare_periods(populated_db, "spo2", "2026-03 vs 2026-02")
        assert result["period_1"]["count"] == 5
