"""Fitbit API client with automatic token refresh and rate limit handling.

All Fitbit Web API endpoints use GET with Bearer token auth.
Rate limit: 150 requests/hour. Headers: Fitbit-Rate-Limit-Remaining,
Fitbit-Rate-Limit-Reset (seconds until reset).
"""

import json
import logging
import time
import urllib.error
import urllib.request

from .auth import refresh_token
from .config import FITBIT_API_BASE

logger = logging.getLogger(__name__)


class FitbitAuthError(Exception):
    """Token expired or invalid, re-auth needed."""


class FitbitRateLimitError(Exception):
    """Rate limited (429). Retry after reset seconds."""
    def __init__(self, reset_seconds: int = 3600):
        self.reset_seconds = reset_seconds
        super().__init__(f"Rate limited. Retry in {reset_seconds}s.")


class FitbitAPIError(Exception):
    """General API error."""


def get(path: str, retries: int = 3) -> dict:
    """Make an authenticated GET request to the Fitbit API.

    Handles:
    - Automatic token refresh before each call (5-min buffer)
    - 401: refresh token and retry once
    - 429: raise FitbitRateLimitError with reset seconds
    - Other non-200: raise FitbitAPIError

    Returns the parsed JSON response body.
    """
    for attempt in range(retries):
        token = refresh_token()
        url = f"{FITBIT_API_BASE}{path}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Accept-Language": "en_GB",
        })

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())

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

        except urllib.error.URLError as e:
            raise FitbitAPIError(f"Network error. Check your connection.") from e

    raise FitbitAuthError("Authentication failed after retry. Run: fitbit-mcp auth")
