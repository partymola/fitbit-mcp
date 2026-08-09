"""Fitbit OAuth2 PKCE setup and token management.

Fitbit uses PKCE (public client, no client secret).
Access tokens expire in 8 hours, refresh tokens in 90 days.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from .config import (
    CONFIG_DIR,
    FITBIT_AUTH_URL,
    FITBIT_CALLBACK_PORT,
    FITBIT_CONFIG_PATH,
    FITBIT_REDIRECT_URI,
    FITBIT_SCOPES,
    FITBIT_TOKEN_URL,
    FITBIT_TOKENS_PATH,
)

logger = logging.getLogger(__name__)


# RFC 6749 defines the token endpoint's refusals as 400, with 401 for a bad
# client. 403 is deliberately absent: a WAF or bot-protection block returns it
# with no opinion about the grant, and this client already reads 403 on a data
# request as something else entirely.
_REFUSAL_CODES = frozenset({400, 401})


class TokenRefused(RuntimeError):
    """The server judged the credentials and rejected them.

    The only failure that warrants telling the user to re-authorise, which
    rewrites the token file the syncing host owns.
    """


class RefreshNetworkError(RuntimeError):
    """The refresh request never got an answer.

    Subclasses RuntimeError so existing callers are unaffected, but is
    distinguishable: an unreachable server says nothing about whether the
    credentials are still good, and telling the user to re-authorise would
    rotate a token file another host may own.
    """


# In-memory token cache to avoid re-reading JSON files on every API call
_cached_tokens = None
_cached_config = None
_token_lock = threading.Lock()


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        # Best-effort: O_TRUNC has already emptied the file, so a
        # permissions failure must not take the token with it.
        if hasattr(os, "fchmod"):
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                logger.warning("Could not tighten permissions on the token file")
        os.write(fd, json.dumps(data, indent=2).encode())
    finally:
        os.close(fd)


def _load_json(path):
    """Read a credential file as a dict, or say why the credentials are unusable.

    Classified here rather than left to the caller: a file that is absent,
    unreadable or not a JSON object means there are no usable credentials,
    which is a refusal - unlike a transport failure, it will not clear on its
    own and the user does have to re-authorise.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise TokenRefused(f"{path.name} is missing or unreadable. Run: fitbit-mcp auth") from e
    if not isinstance(data, dict):
        raise TokenRefused(f"{path.name} is malformed. Run: fitbit-mcp auth")
    return data


def _generate_pkce():
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _refresh_token() -> str:
    """Return a valid access token, refreshing if expired.

    Checks expiry with a 5-minute buffer. If expired, uses the refresh_token
    grant to obtain new tokens and updates the token file.

    Thread-safe: concurrent callers will serialize on _token_lock, so only
    one refresh HTTP call is made even if multiple threads detect expiry.
    """
    global _cached_tokens, _cached_config

    with _token_lock:
        if _cached_tokens is None:
            _cached_tokens = _load_json(FITBIT_TOKENS_PATH)
        if _cached_config is None:
            _cached_config = _load_json(FITBIT_CONFIG_PATH)

        # A non-numeric expiry - hand-edited, or half-repaired - counts as
        # expired rather than raising on the comparison, so the refresh below
        # decides.
        expires_at = _cached_tokens.get("expires_at", 0)
        if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
            expires_at = 0
        if time.time() < expires_at - 300:
            return _cached_tokens["access_token"]

        if not _cached_tokens.get("refresh_token"):
            raise TokenRefused("Token expired and no refresh token. Run: fitbit-mcp auth")

        data = urlencode(
            {
                "grant_type": "refresh_token",
                "client_id": _cached_config["client_id"],
                "refresh_token": _cached_tokens["refresh_token"],
            }
        ).encode()

        req = urllib.request.Request(
            FITBIT_TOKEN_URL,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            # Checked before OSError, which it subclasses. Listed by what the
            # code says about the credentials rather than by range: a bad grant
            # is refused with 400/401/403, while 429 is the rate limit this API
            # applies liberally and carries no judgement. Answering that with
            # "re-authorise" rotates a token file the syncing host owns.
            if e.code in _REFUSAL_CODES:
                raise TokenRefused("Token refresh failed. Run: fitbit-mcp auth") from e
            raise RefreshNetworkError("Fitbit could not answer the refresh request.") from e
        except OSError as e:
            # Not just URLError: urlopen wraps only connect-phase failures in
            # it, so a read timeout or a reset connection arrives bare. Those
            # are the commonest network failures, and classing them as auth
            # would answer a dropped connection by rotating a shared token file.
            raise RefreshNetworkError("Could not reach Fitbit to refresh the token.") from e

        try:
            new_tokens = json.loads(raw)
        except ValueError as e:
            # A proxy or captive portal answering 200 with HTML is a network
            # condition, not a rejected credential.
            raise RefreshNetworkError("Fitbit returned an unreadable response.") from e

        if not isinstance(new_tokens, dict) or not new_tokens.get("access_token"):
            raise TokenRefused("Token refresh failed. Run: fitbit-mcp auth")

        _cached_tokens = {
            "access_token": new_tokens["access_token"],
            "refresh_token": new_tokens.get("refresh_token", _cached_tokens["refresh_token"]),
            "user_id": new_tokens.get("user_id", _cached_tokens.get("user_id")),
            "expires_at": time.time() + new_tokens.get("expires_in", 28800),
        }
        _save_json(FITBIT_TOKENS_PATH, _cached_tokens)
        logger.info("Token refreshed successfully")
        return _cached_tokens["access_token"]


def refresh_token() -> str:
    """Return a valid access token, refreshing if expired.

    Raises exactly two types: TokenRefused, and RefreshNetworkError for
    everything else. Never replace the catch-all with a list of exception
    types - anything unanticipated then reads as a dead credential, and that
    answer rotates a shared token file.
    """
    try:
        return _refresh_token()
    except (TokenRefused, RefreshNetworkError):
        raise
    except Exception as e:
        logger.error("Token refresh failed: %s", type(e).__name__)
        raise RefreshNetworkError("Could not obtain a token from Fitbit.") from e


def invalidate_token_cache():
    """Clear the in-memory token cache, forcing a re-read on the next API call."""
    global _cached_tokens
    with _token_lock:
        _cached_tokens = None


def setup_auth():
    """Interactive OAuth setup. Prompts for client ID, opens browser, exchanges code."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config = None
    if FITBIT_CONFIG_PATH.exists():
        config = _load_json(FITBIT_CONFIG_PATH)
        print(f"Existing client_id: {config['client_id']}")
        resp = input("Re-use existing client ID? [Y/n] ").strip().lower()
        if resp in ("n", "no"):
            config = None

    if not config:
        print("Register a personal app at https://dev.fitbit.com/apps")
        print("Set OAuth 2.0 Application Type to: Personal")
        print(f"Set Redirect URL to: {FITBIT_REDIRECT_URI}")
        client_id = input("Client ID: ").strip()
        if not client_id:
            print("Error: client_id required.", file=sys.stderr)
            sys.exit(1)
        config = {"client_id": client_id}
        _save_json(FITBIT_CONFIG_PATH, config)
        print("Client ID saved.")

    verifier, challenge = _generate_pkce()
    auth_result = {"tokens": None, "error": None}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)

            code = qs.get("code", [None])[0]
            if not code:
                error = qs.get("error", ["unknown"])[0]
                self._respond(400, f"Error: {error}")
                auth_result["error"] = error
                return

            # Exchange code for tokens
            data = urlencode(
                {
                    "client_id": config["client_id"],
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": FITBIT_REDIRECT_URI,
                }
            ).encode()

            req = urllib.request.Request(
                FITBIT_TOKEN_URL,
                data=data,
                method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    tokens = json.loads(r.read().decode())
                self._respond(200, "Authorised! You can close this tab.")
                auth_result["tokens"] = tokens
            except Exception as e:
                self._respond(500, f"Token exchange failed: {e}")
                auth_result["error"] = str(e)

        def _respond(self, status_code, message):
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>{message}</h2></body></html>".encode())

        def log_message(self, format, *args):
            pass

    auth_url = (
        FITBIT_AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": config["client_id"],
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "redirect_uri": FITBIT_REDIRECT_URI,
                "scope": FITBIT_SCOPES,
            }
        )
    )

    print("\nOpening browser for Fitbit auth...")
    print(f"If it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", FITBIT_CALLBACK_PORT), CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=120)
    server.server_close()

    if auth_result["error"]:
        print(f"Authorisation failed: {auth_result['error']}", file=sys.stderr)
        sys.exit(1)

    if not auth_result["tokens"]:
        print("No response received. Timed out or denied.", file=sys.stderr)
        sys.exit(1)

    raw = auth_result["tokens"]
    token_store = {
        "access_token": raw["access_token"],
        "refresh_token": raw.get("refresh_token", ""),
        "user_id": raw.get("user_id"),
        "expires_at": time.time() + raw.get("expires_in", 28800),
    }
    _save_json(FITBIT_TOKENS_PATH, token_store)
    print(f"Tokens saved. User ID: {raw.get('user_id')}")
    print("\nSetup complete. Register with Claude Code:")
    import shutil

    exe = shutil.which("fitbit-mcp") or "fitbit-mcp"
    print(f"  claude mcp add -s user fitbit -- {exe}")
