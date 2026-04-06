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
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

from .config import (
    CONFIG_DIR, FITBIT_CONFIG_PATH, FITBIT_TOKENS_PATH,
    FITBIT_AUTH_URL, FITBIT_TOKEN_URL, FITBIT_SCOPES,
    FITBIT_CALLBACK_PORT, FITBIT_REDIRECT_URI,
)

logger = logging.getLogger(__name__)

# In-memory token cache to avoid re-reading JSON files on every API call
_cached_tokens = None
_cached_config = None
_token_lock = threading.Lock()


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(data, indent=2).encode())
    finally:
        os.close(fd)


def _load_json(path):
    return json.loads(path.read_text())


def _generate_pkce():
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def refresh_token() -> str:
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

        expires_at = _cached_tokens.get("expires_at", 0)
        if time.time() < expires_at - 300:
            return _cached_tokens["access_token"]

        if not _cached_tokens.get("refresh_token"):
            raise RuntimeError("Token expired and no refresh token. Run: fitbit-mcp auth")

        data = urlencode({
            "grant_type": "refresh_token",
            "client_id": _cached_config["client_id"],
            "refresh_token": _cached_tokens["refresh_token"],
        }).encode()

        req = urllib.request.Request(FITBIT_TOKEN_URL, data=data, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded",
        })

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                new_tokens = json.loads(resp.read().decode())
        except urllib.error.URLError as e:
            raise RuntimeError("Token refresh failed. Run: fitbit-mcp auth") from e

        if "access_token" not in new_tokens:
            raise RuntimeError("Token refresh failed. Run: fitbit-mcp auth")

        _cached_tokens = {
            "access_token": new_tokens["access_token"],
            "refresh_token": new_tokens.get("refresh_token", _cached_tokens["refresh_token"]),
            "user_id": new_tokens.get("user_id", _cached_tokens.get("user_id")),
            "expires_at": time.time() + new_tokens.get("expires_in", 28800),
        }
        _save_json(FITBIT_TOKENS_PATH, _cached_tokens)
        logger.info("Token refreshed successfully")
        return _cached_tokens["access_token"]


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
        print(f"Set OAuth 2.0 Application Type to: Personal")
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
            data = urlencode({
                "client_id": config["client_id"],
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": FITBIT_REDIRECT_URI,
            }).encode()

            req = urllib.request.Request(FITBIT_TOKEN_URL, data=data, method="POST", headers={
                "Content-Type": "application/x-www-form-urlencoded",
            })
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
            self.wfile.write(
                f"<html><body><h2>{message}</h2></body></html>".encode()
            )

        def log_message(self, format, *args):
            pass

    auth_url = FITBIT_AUTH_URL + "?" + urlencode({
        "client_id": config["client_id"],
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": FITBIT_REDIRECT_URI,
        "scope": FITBIT_SCOPES,
    })

    print(f"\nOpening browser for Fitbit auth...")
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
