"""Tests for the Fitbit API client."""

import json
from unittest.mock import patch, MagicMock
from http.client import HTTPResponse

import pytest

from fitbit_mcp.api import get, FitbitAuthError, FitbitRateLimitError, FitbitAPIError


class TestAPIExceptions:
    """Test exception hierarchy."""

    def test_auth_error(self):
        e = FitbitAuthError("test")
        assert str(e) == "test"

    def test_rate_limit_error_default(self):
        e = FitbitRateLimitError()
        assert e.reset_seconds == 3600

    def test_rate_limit_error_custom(self):
        e = FitbitRateLimitError(120)
        assert e.reset_seconds == 120
        assert "120" in str(e)

    def test_api_error(self):
        e = FitbitAPIError("bad request")
        assert "bad request" in str(e)


class TestAPIGet:
    """Test the authenticated GET function."""

    @patch("fitbit_mcp.api.refresh_token")
    @patch("fitbit_mcp.api.urllib.request.urlopen")
    def test_successful_get(self, mock_urlopen, mock_refresh):
        mock_refresh.return_value = "test_token"
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"data": "ok"}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = get("/1/user/-/test.json")
        assert result == {"data": "ok"}

        # Verify correct URL and Authorization header were used
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://api.fitbit.com/1/user/-/test.json"
        assert req.get_header("Authorization") == "Bearer test_token"

    @patch("fitbit_mcp.auth.invalidate_token_cache")
    @patch("fitbit_mcp.api.refresh_token")
    @patch("fitbit_mcp.api.urllib.request.urlopen")
    def test_401_retries(self, mock_urlopen, mock_refresh, mock_invalidate):
        import urllib.error
        mock_refresh.return_value = "token"

        ok_response = MagicMock()
        ok_response.read.return_value = json.dumps({"ok": True}).encode()
        ok_response.__enter__ = MagicMock(return_value=ok_response)
        ok_response.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [
            urllib.error.HTTPError("url", 401, "Unauthorized", {}, None),
            ok_response,
        ]

        result = get("/1/user/-/test.json")
        assert result == {"ok": True}
        # Verify cache was invalidated so the next attempt fetches a fresh token
        mock_invalidate.assert_called_once()

    @patch("fitbit_mcp.api.refresh_token")
    @patch("fitbit_mcp.api.urllib.request.urlopen")
    def test_429_raises_rate_limit(self, mock_urlopen, mock_refresh):
        import urllib.error
        mock_refresh.return_value = "token"

        headers = {"Fitbit-Rate-Limit-Reset": "300"}
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 429, "Too Many Requests", headers, None
        )

        with pytest.raises(FitbitRateLimitError) as exc_info:
            get("/1/user/-/test.json")
        assert exc_info.value.reset_seconds == 300

    @patch("fitbit_mcp.api.refresh_token")
    @patch("fitbit_mcp.api.urllib.request.urlopen")
    def test_500_raises_api_error(self, mock_urlopen, mock_refresh):
        import urllib.error
        mock_refresh.return_value = "token"

        error = urllib.error.HTTPError("url", 500, "Internal Server Error", {}, None)
        error.read = MagicMock(return_value=b"server error")
        mock_urlopen.side_effect = error

        with pytest.raises(FitbitAPIError, match="500"):
            get("/1/user/-/test.json")

    @patch("fitbit_mcp.api.refresh_token")
    @patch("fitbit_mcp.api.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen, mock_refresh):
        import urllib.error
        mock_refresh.return_value = "token"
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        with pytest.raises(FitbitAPIError, match="Network error"):
            get("/1/user/-/test.json")

    @patch("fitbit_mcp.api.refresh_token")
    @patch("fitbit_mcp.api.urllib.request.urlopen")
    def test_401_exhausts_retries(self, mock_urlopen, mock_refresh):
        import urllib.error
        mock_refresh.return_value = "token"
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, None
        )

        with pytest.raises(FitbitAuthError):
            get("/1/user/-/test.json", retries=2)
