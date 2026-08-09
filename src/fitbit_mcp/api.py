"""Fitbit API client with automatic token refresh and rate limit handling.

All Fitbit Web API endpoints use GET with Bearer token auth.
Rate limit: 150 requests/hour. Headers: Fitbit-Rate-Limit-Remaining,
Fitbit-Rate-Limit-Reset (seconds until reset).

Accept-Language is intentionally not set: Fitbit returns metric units
(kg, km, cm, C) by default. Setting `en_GB` returns weight in stones
even though distance stays in km.
"""

import json
import logging
import time
import urllib.error
import urllib.request

from . import config
from .auth import RefreshNetworkError, TokenRefused, refresh_token
from .config import FITBIT_API_BASE

logger = logging.getLogger(__name__)


class FitbitAuthError(Exception):
    """Token expired or invalid, re-auth needed."""


class FitbitOfflineError(Exception):
    """A live API call was attempted while offline/cache-only mode is on.

    Deliberately subclasses Exception directly and NOT FitbitAPIError /
    FitbitAuthError / FitbitRateLimitError: run_sync() catches those per data
    type, which would swallow this and write spurious error rows to the cache.
    It is meant to propagate up to require_auth (and the CLI sync handler),
    which translate it into a single clean "offline mode" message.
    """


class FitbitRateLimitError(Exception):
    """Rate limited (429). Retry after reset seconds."""

    def __init__(self, reset_seconds: int = 3600):
        self.reset_seconds = reset_seconds
        super().__init__(f"Rate limited. Retry in {reset_seconds}s.")


class FitbitAPIError(Exception):
    """General API error."""


def get(path: str, retries: int = 3) -> dict | list:
    """Make an authenticated GET request to the Fitbit API.

    Handles:
    - Automatic token refresh before each call (5-min buffer)
    - 401: refresh token and retry once
    - 429: raise FitbitRateLimitError with reset seconds
    - Transient network errors / read timeouts: retry with exponential backoff
    - Other non-200: raise FitbitAPIError

    Returns the parsed JSON response body.
    """
    if config.OFFLINE_MODE:
        raise FitbitOfflineError(
            "Offline mode is on (FITBIT_MCP_OFFLINE); live API calls are disabled. "
            "Query the local cache instead, or unset FITBIT_MCP_OFFLINE."
        )

    for attempt in range(retries):
        # refresh_token reports its documented failures with builtins, which
        # run_sync does not classify; translated here, at its only call site.
        # The messages are fixed rather than built from the original, which can
        # carry a path or file content into the sync log.
        try:
            token = refresh_token()
        except TokenRefused as e:
            raise FitbitAuthError("Could not obtain an access token. Run: fitbit-mcp auth") from e
        except RefreshNetworkError as e:
            # Not an auth failure: an unreachable server says nothing about the
            # credentials, and advising re-auth would rotate a token file the
            # syncing host owns.
            raise FitbitAPIError("Network error. Check your connection.") from e
        url = f"{FITBIT_API_BASE}{path}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()

        except urllib.error.HTTPError as e:
            if e.code == 401:
                if attempt < retries - 1:
                    logger.info("Token expired (401), refreshing")
                    from . import auth

                    auth.invalidate_token_cache()
                    continue
                raise FitbitAuthError("Authentication failed after retry. Run: fitbit-mcp auth")

            if e.code == 429:
                reset_secs = int(e.headers.get("Fitbit-Rate-Limit-Reset", 3600))
                raise FitbitRateLimitError(reset_secs)

            body = ""
            try:
                body = e.read().decode()[:200]
            except Exception:
                pass
            raise FitbitAPIError(f"API error {e.code} for {path}: {body}")

        # A read timeout raises bare TimeoutError (not wrapped in URLError); a
        # connection-level failure raises URLError. Both are transient for an
        # idempotent GET, so retry with backoff (2s, 4s) before giving up.
        except (TimeoutError, urllib.error.URLError) as e:
            if attempt < retries - 1:
                backoff = 2 ** (attempt + 1)
                logger.warning("Network error (%s), retrying in %ss", e, backoff)
                time.sleep(backoff)
                continue
            raise FitbitAPIError(f"Network error after {retries} attempts: {e}") from e

        # Parsing is its own failure cause, not a transport one, and it is
        # left to json.loads on the raw bytes so that an undecodable body and
        # one that is not JSON land in the same place: both raise ValueError,
        # which none of the handlers above catch. Either used to escape
        # run_sync - no sync_log row, and doctor reporting a clean log while
        # the cache aged.
        try:
            body = json.loads(raw)
        except ValueError as e:
            raise FitbitAPIError("Fitbit returned an unreadable response.") from e

        # A list is a legitimate response here, not a fault: /devices.json
        # returns a bare array, and the spo2 range endpoint returns either an
        # array or an object. Only a scalar - a bare string, number, null - is
        # a shape no caller can use, and it would otherwise fail at their
        # .get() or iteration, past run_sync's handlers.
        if not isinstance(body, (dict, list)):
            raise FitbitAPIError("Fitbit returned an unexpected response shape.")

        return body

    raise FitbitAuthError("Authentication failed after retry. Run: fitbit-mcp auth")
