"""Tests for the Fitbit API client."""

import json
from unittest.mock import MagicMock, patch

import pytest

from fitbit_mcp import api, auth, config
from fitbit_mcp.api import (
    FitbitAPIError,
    FitbitAuthError,
    FitbitOfflineError,
    FitbitRateLimitError,
    get,
)


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
        # Accept-Language must not be en_GB: Fitbit returns weight in stones
        # for that locale. Omitting the header gives full metric (kg, km).
        assert req.get_header("Accept-language") is None

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
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

        with pytest.raises(FitbitAuthError):
            get("/1/user/-/test.json", retries=2)


class TestOfflineMode:
    """Live API access is refused in offline / cache-only mode."""

    def test_offline_error_not_a_caught_api_error(self):
        # run_sync() catches FitbitAPIError/Auth/RateLimit per data type. If
        # FitbitOfflineError subclassed any of them it would be swallowed into
        # per-type error rows instead of propagating to require_auth/CLI.
        assert not issubclass(
            FitbitOfflineError,
            (FitbitAPIError, FitbitAuthError, FitbitRateLimitError),
        )

    @patch("fitbit_mcp.api.refresh_token")
    @patch("fitbit_mcp.api.urllib.request.urlopen")
    def test_get_raises_offline_before_any_network(self, mock_urlopen, mock_refresh, monkeypatch):
        monkeypatch.setattr("fitbit_mcp.config.OFFLINE_MODE", True)
        with pytest.raises(FitbitOfflineError):
            get("/1/user/-/test.json")
        # The raise must happen before the token refresh and the network call.
        mock_refresh.assert_not_called()
        mock_urlopen.assert_not_called()

    @patch("fitbit_mcp.api.refresh_token")
    @patch("fitbit_mcp.api.urllib.request.urlopen")
    def test_get_normal_when_not_offline(self, mock_urlopen, mock_refresh, monkeypatch):
        # Regression guard: with the flag off, the network path is reached.
        monkeypatch.setattr("fitbit_mcp.config.OFFLINE_MODE", False)
        mock_refresh.return_value = "test_token"
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"data": "ok"}).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        assert get("/1/user/-/test.json") == {"data": "ok"}
        mock_refresh.assert_called()
        mock_urlopen.assert_called()


class TestRefreshFailuresAreClassified:
    """api.get maps the two types refresh_token guarantees, and nothing else.

    It used to catch a tuple of builtins, which meant the classification
    depended on remembering every type auth could raise - the reason a bare
    OSError, an http.client exception and a decode failure were each graded a
    dead credential in turn. refresh_token now classifies at its own boundary,
    so there is no tuple here to get wrong.
    """

    def _get_with_refresh_raising(self, exc, monkeypatch):
        monkeypatch.setattr(config, "OFFLINE_MODE", False)
        with patch("fitbit_mcp.api.refresh_token", side_effect=exc):
            return api.get("/1/user/-/profile.json")

    def test_a_refusal_becomes_an_auth_error(self, monkeypatch):
        with pytest.raises(FitbitAuthError):
            self._get_with_refresh_raising(auth.TokenRefused("no"), monkeypatch)

    def test_a_network_failure_is_not_an_auth_failure(self, monkeypatch):
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_refresh_raising(auth.RefreshNetworkError("no route"), monkeypatch)
        assert not isinstance(caught.value, FitbitAuthError)

    def test_the_auth_message_is_fixed_text(self, monkeypatch):
        """sync_log stores this string, so nothing may be interpolated."""
        with pytest.raises(FitbitAuthError) as caught:
            self._get_with_refresh_raising(
                auth.TokenRefused("/etc/secret/path is missing"), monkeypatch
            )
        assert str(caught.value) == "Could not obtain an access token. Run: fitbit-mcp auth"

    def test_the_network_message_is_fixed_text(self, monkeypatch):
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_refresh_raising(
                auth.RefreshNetworkError("/etc/secret/path timed out"), monkeypatch
            )
        assert str(caught.value) == "Network error. Check your connection."


class TestTheRefreshBoundary:
    """Every exit from refresh_token is one of two types, by construction.

    Enumerating exception types is what failed repeatedly; this asserts the
    property that replaced the enumeration, including for a type nobody
    anticipated.
    """

    def _refresh_with_worker_raising(self, exc, monkeypatch):
        monkeypatch.setattr(auth, "_refresh_token", MagicMock(side_effect=exc))
        return auth.refresh_token()

    @pytest.mark.parametrize(
        "exc",
        [
            TimeoutError("bare timeout"),
            ConnectionResetError("reset"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"),
            KeyError("access_token"),
            ValueError("unparseable"),
            RuntimeError("something nobody classified"),
        ],
        ids=["timeout", "reset", "undecodable", "keyerror", "valueerror", "runtime"],
    )
    def test_an_unclassified_failure_becomes_a_network_error(self, exc, monkeypatch):
        with pytest.raises(auth.RefreshNetworkError):
            self._refresh_with_worker_raising(exc, monkeypatch)

    def test_a_truncated_response_becomes_a_network_error(self, monkeypatch):
        """http.client exceptions are not OSError, so they escaped every tuple."""
        import http.client

        with pytest.raises(auth.RefreshNetworkError):
            self._refresh_with_worker_raising(http.client.BadStatusLine("garbage"), monkeypatch)

    def test_a_refusal_is_passed_through_unchanged(self, monkeypatch):
        with pytest.raises(auth.TokenRefused):
            self._refresh_with_worker_raising(auth.TokenRefused("revoked"), monkeypatch)

    def test_the_boundary_does_not_swallow_a_successful_refresh(self, monkeypatch):
        monkeypatch.setattr(auth, "_refresh_token", MagicMock(return_value="a-token"))
        assert auth.refresh_token() == "a-token"


class TestAgainstTheRealRefresh:
    """Drive the real auth.refresh_token, so the catch tuple is a fact.

    Every test above injects a side effect, which pins what api.get does with
    an exception but not that auth actually raises that kind. A broken token
    file exercised end to end is what proves the two agree.
    """

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "OFFLINE_MODE", False)
        monkeypatch.setattr(auth, "_cached_tokens", None)
        monkeypatch.setattr(auth, "_cached_config", None)
        self.dir = tmp_path
        yield
        auth._cached_tokens = None
        auth._cached_config = None

    def _get_with_token_file(self, contents, monkeypatch):
        tokens = self.dir / "fitbit_tokens.json"
        conf = self.dir / "fitbit_config.json"
        if contents is not None:
            tokens.write_text(contents)
        conf.write_text('{"client_id": "FAKEID"}')
        monkeypatch.setattr(auth, "FITBIT_TOKENS_PATH", tokens)
        monkeypatch.setattr(auth, "FITBIT_CONFIG_PATH", conf)
        return api.get("/1/user/-/profile.json")

    def test_a_missing_token_file(self, monkeypatch):
        with pytest.raises(FitbitAuthError):
            self._get_with_token_file(None, monkeypatch)

    def test_a_token_file_that_is_not_json(self, monkeypatch):
        with pytest.raises(FitbitAuthError):
            self._get_with_token_file("{not json", monkeypatch)

    def test_a_token_file_that_is_not_an_object(self, monkeypatch):
        """Valid JSON of the wrong shape used to fail at an attribute access."""
        with pytest.raises(FitbitAuthError):
            self._get_with_token_file('["not", "an", "object"]', monkeypatch)

    def test_a_token_file_with_a_non_numeric_expiry(self, monkeypatch):
        """A hand-edited expires_at used to raise TypeError on the comparison."""
        with pytest.raises(FitbitAuthError):
            self._get_with_token_file('{"access_token": "a", "expires_at": "soon"}', monkeypatch)

    def test_a_token_file_with_no_refresh_token(self, monkeypatch):
        with pytest.raises(FitbitAuthError):
            self._get_with_token_file('{"access_token": "a", "expires_at": 0}', monkeypatch)

    def test_a_refresh_that_cannot_reach_fitbit_is_not_an_auth_failure(self, monkeypatch):
        """Driven through the real auth code, not an injected exception type."""
        import urllib.error

        monkeypatch.setattr(
            auth.urllib.request, "urlopen", MagicMock(side_effect=urllib.error.URLError("no route"))
        )
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_token_file(
                '{"access_token": "a", "refresh_token": "r", "expires_at": 0}', monkeypatch
            )
        assert not isinstance(caught.value, FitbitAuthError)

    def _http_error(self, code):
        import io
        import urllib.error

        return urllib.error.HTTPError("https://example.invalid", code, "no", {}, io.BytesIO(b""))

    def test_a_revoked_token_is_an_auth_failure_not_a_network_one(self, monkeypatch):
        """HTTPError subclasses URLError, so this is the case that inverts."""
        monkeypatch.setattr(
            auth.urllib.request, "urlopen", MagicMock(side_effect=self._http_error(400))
        )
        with pytest.raises(FitbitAuthError):
            self._get_with_token_file(
                '{"access_token": "a", "refresh_token": "r", "expires_at": 0}', monkeypatch
            )

    def test_a_rate_limit_is_not_an_auth_failure(self, monkeypatch):
        """429 is a 4xx that carries no judgement on the credentials.

        Answering it with re-authorisation turns a condition that clears
        itself into a rotated token file on the host that syncs.
        """
        monkeypatch.setattr(
            auth.urllib.request, "urlopen", MagicMock(side_effect=self._http_error(429))
        )
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_token_file(
                '{"access_token": "a", "refresh_token": "r", "expires_at": 0}', monkeypatch
            )
        assert not isinstance(caught.value, FitbitAuthError)

    def test_a_server_side_failure_is_not_an_auth_failure(self, monkeypatch):
        monkeypatch.setattr(
            auth.urllib.request, "urlopen", MagicMock(side_effect=self._http_error(503))
        )
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_token_file(
                '{"access_token": "a", "refresh_token": "r", "expires_at": 0}', monkeypatch
            )
        assert not isinstance(caught.value, FitbitAuthError)

    def test_a_read_timeout_is_a_network_failure(self, monkeypatch):
        """The body read happens after urlopen returns, so this arrives bare."""
        monkeypatch.setattr(
            auth.urllib.request, "urlopen", MagicMock(side_effect=TimeoutError("timed out"))
        )
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_token_file(
                '{"access_token": "a", "refresh_token": "r", "expires_at": 0}', monkeypatch
            )
        assert not isinstance(caught.value, FitbitAuthError)

    def test_a_reset_connection_is_a_network_failure(self, monkeypatch):
        monkeypatch.setattr(
            auth.urllib.request, "urlopen", MagicMock(side_effect=ConnectionResetError("reset"))
        )
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_token_file(
                '{"access_token": "a", "refresh_token": "r", "expires_at": 0}', monkeypatch
            )
        assert not isinstance(caught.value, FitbitAuthError)

    def _urlopen_returning(self, payload):
        response = MagicMock()
        response.read.return_value = payload
        response.__enter__ = lambda s: s
        response.__exit__ = lambda *a: None
        return MagicMock(return_value=response)

    def test_a_response_that_is_not_json_is_a_network_failure(self, monkeypatch):
        """A captive portal answering 200 with HTML is not a bad credential."""
        monkeypatch.setattr(
            auth.urllib.request, "urlopen", self._urlopen_returning(b"<html>wifi login</html>")
        )
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_token_file(
                '{"access_token": "a", "refresh_token": "r", "expires_at": 0}', monkeypatch
            )
        assert not isinstance(caught.value, FitbitAuthError)

    def test_a_response_of_the_wrong_shape_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(
            auth.urllib.request, "urlopen", self._urlopen_returning(b'["not", "an", "object"]')
        )
        with pytest.raises(FitbitAuthError):
            self._get_with_token_file(
                '{"access_token": "a", "refresh_token": "r", "expires_at": 0}', monkeypatch
            )

    def test_the_network_message_is_fixed_text(self, monkeypatch):
        """run_sync stores this string, so nothing may be interpolated into it.

        Asserted as equality rather than absence: the message a caller sees is
        rebuilt at each layer, so checking only that one particular path is
        missing would pass however much else leaked in.
        """
        monkeypatch.setattr(
            auth.urllib.request,
            "urlopen",
            MagicMock(side_effect=TimeoutError("/etc/secret/path timed out")),
        )
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_token_file(
                '{"access_token": "a", "refresh_token": "r", "expires_at": 0}', monkeypatch
            )
        assert str(caught.value) == "Network error. Check your connection."


class TestAgainstRealTransportFailures:
    """The shapes that escaped every enumerated tuple, through real auth code."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "OFFLINE_MODE", False)
        monkeypatch.setattr(auth, "_cached_tokens", None)
        monkeypatch.setattr(auth, "_cached_config", None)
        tokens = tmp_path / "fitbit_tokens.json"
        conf = tmp_path / "fitbit_config.json"
        tokens.write_text('{"access_token": "a", "refresh_token": "r", "expires_at": 0}')
        conf.write_text('{"client_id": "FAKEID"}')
        monkeypatch.setattr(auth, "FITBIT_TOKENS_PATH", tokens)
        monkeypatch.setattr(auth, "FITBIT_CONFIG_PATH", conf)

    def _get_with_response(self, payload, monkeypatch):
        response = MagicMock()
        response.read.return_value = payload
        response.__enter__ = lambda s: s
        response.__exit__ = lambda *a: None
        monkeypatch.setattr(auth.urllib.request, "urlopen", MagicMock(return_value=response))
        return api.get("/1/user/-/profile.json")

    def test_an_undecodable_body_is_not_an_auth_failure(self, monkeypatch):
        """UnicodeDecodeError is a ValueError, which used to read as a refusal."""
        with pytest.raises(FitbitAPIError) as caught:
            self._get_with_response(b"\xe9\xff not utf-8", monkeypatch)
        assert not isinstance(caught.value, FitbitAuthError)

    def test_a_non_http_response_is_not_an_auth_failure(self, monkeypatch):
        import http.client

        monkeypatch.setattr(
            auth.urllib.request,
            "urlopen",
            MagicMock(side_effect=http.client.BadStatusLine("GARBAGE NOT HTTP")),
        )
        with pytest.raises(FitbitAPIError) as caught:
            api.get("/1/user/-/profile.json")
        assert not isinstance(caught.value, FitbitAuthError)

    def test_a_null_access_token_is_refused_not_returned(self, monkeypatch):
        """A null token used to pass the presence check and be written to disk."""
        with pytest.raises(FitbitAuthError):
            self._get_with_response(b'{"access_token": null}', monkeypatch)

    def test_a_forbidden_response_is_not_a_refusal(self, monkeypatch):
        """403 is what a WAF returns; it says nothing about the grant."""
        import io
        import urllib.error

        monkeypatch.setattr(
            auth.urllib.request,
            "urlopen",
            MagicMock(
                side_effect=urllib.error.HTTPError(
                    "https://example.invalid", 403, "blocked", {}, io.BytesIO(b"")
                )
            ),
        )
        with pytest.raises(FitbitAPIError) as caught:
            api.get("/1/user/-/profile.json")
        assert not isinstance(caught.value, FitbitAuthError)
