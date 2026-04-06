"""Tests for helpers module: date parsing, formatting, response formatting."""

from datetime import date, timedelta

import pytest

from fitbit_mcp.helpers import parse_date, format_duration, format_response


class TestParseDate:
    """Tests for the flexible date parser."""

    def test_defaults_30_days(self):
        start, end = parse_date(None, None, default_days=30)
        assert end == date.today()
        assert start == date.today() - timedelta(days=30)

    def test_defaults_custom_days(self):
        start, end = parse_date(None, None, default_days=7)
        assert start == date.today() - timedelta(days=7)

    def test_iso_date(self):
        start, end = parse_date("2026-01-15", "2026-02-20")
        assert start == date(2026, 1, 15)
        assert end == date(2026, 2, 20)

    def test_relative_start(self):
        start, end = parse_date("7d", None)
        assert start == date.today() - timedelta(days=7)
        assert end == date.today()

    def test_relative_both(self):
        start, end = parse_date("30d", "7d")
        assert start == date.today() - timedelta(days=30)
        assert end == date.today() - timedelta(days=7)

    def test_month_start(self):
        start, _ = parse_date("2026-03", None)
        assert start == date(2026, 3, 1)

    def test_month_end(self):
        _, end = parse_date(None, "2026-03")
        assert end == date(2026, 3, 31)

    def test_month_end_february_leap(self):
        _, end = parse_date(None, "2028-02")
        assert end == date(2028, 2, 29)

    def test_month_end_february_non_leap(self):
        _, end = parse_date(None, "2027-02")
        assert end == date(2027, 2, 28)

    def test_month_end_december(self):
        _, end = parse_date(None, "2026-12")
        assert end == date(2026, 12, 31)

    def test_month_start_january(self):
        start, _ = parse_date("2026-01", None)
        assert start == date(2026, 1, 1)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid date"):
            parse_date("not-a-date", None)

    def test_invalid_relative_raises(self):
        with pytest.raises(ValueError, match="Invalid date"):
            parse_date("30x", None)

    def test_start_after_end_allowed(self):
        """Parser doesn't validate that start < end."""
        start, end = parse_date("2026-03-15", "2026-01-01")
        assert start > end


class TestFormatDuration:
    """Tests for the duration formatter."""

    def test_none_returns_empty(self):
        assert format_duration(None) == ""

    def test_zero(self):
        assert format_duration(0) == "0m"

    def test_minutes_only(self):
        assert format_duration(45) == "45m"

    def test_hours_and_minutes(self):
        assert format_duration(90) == "1h 30m"

    def test_exact_hours(self):
        assert format_duration(120) == "2h 0m"

    def test_float_rounds_correctly(self):
        assert format_duration(90.7) == "1h 31m"

    def test_float_rounds_down_at_half(self):
        # round() uses banker's rounding, 90.5 -> 90
        assert format_duration(90.5) == "1h 30m"

    def test_large_value(self):
        assert format_duration(1440) == "24h 0m"


class TestFormatResponse:
    """Tests for MCP response formatting."""

    def test_dict(self):
        result = format_response({"key": "value"})
        assert '"key": "value"' in result

    def test_list(self):
        result = format_response([1, 2, 3])
        assert "[" in result

    def test_none(self):
        assert format_response(None) == "null"

    def test_string(self):
        result = format_response("hello")
        assert '"result": "hello"' in result

    def test_nested_dict(self):
        result = format_response({"a": {"b": 1}})
        assert '"b": 1' in result

    def test_date_serialization(self):
        result = format_response({"d": date(2026, 3, 15)})
        assert "2026-03-15" in result
