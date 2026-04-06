"""Tests for the OAuth authentication module."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from fitbit_mcp.auth import _generate_pkce, _save_json, _load_json, refresh_token


class TestPKCE:
    """Test PKCE code verifier/challenge generation."""

    def test_verifier_length(self):
        verifier, _ = _generate_pkce()
        assert 43 <= len(verifier) <= 128

    def test_challenge_is_base64url(self):
        _, challenge = _generate_pkce()
        # Base64url: only alphanumeric, hyphen, underscore (no padding)
        import re
        assert re.match(r'^[A-Za-z0-9_-]+$', challenge)

    def test_different_each_call(self):
        v1, c1 = _generate_pkce()
        v2, c2 = _generate_pkce()
        assert v1 != v2
        assert c1 != c2

    def test_challenge_matches_verifier(self):
        """Verify the challenge is the SHA256 of the verifier."""
        import base64
        import hashlib
        verifier, challenge = _generate_pkce()
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert challenge == expected


class TestSaveLoadJson:
    """Test secure JSON file I/O."""

    def test_save_creates_file(self, tmp_path):
        path = tmp_path / "test.json"
        _save_json(path, {"key": "value"})
        assert path.exists()

    def test_save_permissions(self, tmp_path):
        path = tmp_path / "test.json"
        _save_json(path, {"key": "value"})
        mode = oct(os.stat(path).st_mode & 0o777)
        assert mode == "0o600"

    def test_save_creates_parents(self, tmp_path):
        path = tmp_path / "subdir" / "deep" / "test.json"
        _save_json(path, {"key": "value"})
        assert path.exists()

    def test_roundtrip(self, tmp_path):
        path = tmp_path / "test.json"
        data = {"client_id": "abc123", "nested": {"a": 1}}
        _save_json(path, data)
        loaded = _load_json(path)
        assert loaded == data

    def test_overwrite(self, tmp_path):
        path = tmp_path / "test.json"
        _save_json(path, {"v": 1})
        _save_json(path, {"v": 2})
        loaded = _load_json(path)
        assert loaded["v"] == 2


class TestRefreshToken:
    """Test token refresh logic."""

    def test_returns_cached_if_not_expired(self, tmp_path):
        import fitbit_mcp.auth as auth
        old_cached_tokens = auth._cached_tokens
        old_cached_config = auth._cached_config

        try:
            auth._cached_tokens = {
                "access_token": "valid_token",
                "refresh_token": "refresh_abc",
                "user_id": "USER1",
                "expires_at": time.time() + 3600,  # 1 hour from now
            }
            auth._cached_config = {"client_id": "test_client"}

            token = refresh_token()
            assert token == "valid_token"
        finally:
            auth._cached_tokens = old_cached_tokens
            auth._cached_config = old_cached_config

    def test_raises_if_no_refresh_token(self, tmp_path):
        import fitbit_mcp.auth as auth
        old_cached_tokens = auth._cached_tokens
        old_cached_config = auth._cached_config

        try:
            auth._cached_tokens = {
                "access_token": "expired_token",
                "refresh_token": "",
                "expires_at": time.time() - 600,  # expired
            }
            auth._cached_config = {"client_id": "test_client"}

            with pytest.raises(RuntimeError, match="no refresh token"):
                refresh_token()
        finally:
            auth._cached_tokens = old_cached_tokens
            auth._cached_config = old_cached_config
