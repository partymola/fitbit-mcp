"""Tests for the OAuth authentication module."""

import json
import os
import time

import pytest

from fitbit_mcp.auth import _generate_pkce, _load_json, _save_json, refresh_token


class TestPKCE:
    """Test PKCE code verifier/challenge generation."""

    def test_verifier_length(self):
        verifier, _ = _generate_pkce()
        assert 43 <= len(verifier) <= 128

    def test_challenge_is_base64url(self):
        _, challenge = _generate_pkce()
        # Base64url: only alphanumeric, hyphen, underscore (no padding)
        import re

        assert re.match(r"^[A-Za-z0-9_-]+$", challenge)

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

    def test_overwrite_truncates_rather_than_leaving_a_tail(self, tmp_path):
        """A shorter second payload must not leave bytes from the first.

        Equal-length payloads cannot catch a missing O_TRUNC: the second write
        covers the first exactly. A leftover tail makes the file unparseable,
        which now reads as unusable credentials and sends the user to
        re-authorise - rotating a token file the syncing host owns.
        """
        path = tmp_path / "tokens.json"
        _save_json(path, {"padding": "x" * 500, "v": 1})
        _save_json(path, {"v": 2})
        assert json.loads(path.read_text()) == {"v": 2}


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


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="POSIX mode bits; Windows uses ACLs")
def test_an_existing_loose_token_file_is_tightened(tmp_path):
    """O_CREAT's mode applies only at creation, so upgrades kept 0644.

    An install predating the owner-only write keeps a world-readable refresh
    token until something narrows it, and the user should not have to know to
    run chmod by hand.
    """
    path = tmp_path / "tokens.json"
    path.write_text("{}")
    os.chmod(path, 0o644)

    _save_json(path, {"refresh_token": "fictional"})

    assert oct(path.stat().st_mode & 0o777) == "0o600"


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="POSIX mode bits; Windows uses ACLs")
def test_the_mode_is_set_when_the_file_is_created(tmp_path, monkeypatch):
    """Pins the open mode, not just the final one.

    fchmod corrects the mode afterwards, so asserting the result alone cannot
    tell a file that was never readable from one that was briefly 0666.
    """
    seen = {}
    real_open = os.open

    def spy(path, flags, mode=0o777, **kwargs):
        seen["mode"] = mode
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    _save_json(tmp_path / "tokens.json", {"refresh_token": "fictional"})

    assert oct(seen["mode"]) == "0o600"


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="POSIX mode bits; Windows uses ACLs")
def test_a_chmod_failure_does_not_destroy_the_token(tmp_path, monkeypatch):
    """O_TRUNC has already emptied the file by the time the mode is set.

    Letting a chmod failure abort the write would trade a permissions problem
    for a lost refresh token - and an empty file reads as unusable
    credentials, which sends the user to re-authorise.
    """

    def refuse(fd, mode):
        raise PermissionError("not the owner")

    monkeypatch.setattr(os, "fchmod", refuse)
    path = tmp_path / "tokens.json"
    _save_json(path, {"refresh_token": "fictional"})

    assert json.loads(path.read_text()) == {"refresh_token": "fictional"}


class TestTheCallbackPage:
    """What the browser authorisation flow shows the user.

    The callback reflects a query-string parameter back to the browser, so
    the page escapes what it displays. The two assertions below that go
    wider - reading setup_auth's source rather than calling it - keep the
    exception itself out of that page and out of stderr, by the two routes
    it can travel: bound to a name, and reached without one.
    """

    def test_a_script_tag_is_escaped(self):
        from fitbit_mcp.auth import _callback_page

        page = _callback_page("Error: <script>alert(1)</script>")
        assert "<script>" not in page
        assert "&lt;script&gt;" in page

    def test_the_handler_builds_its_page_through_the_helper(self):
        """The helper being correct is no use if the handler stops calling it.

        The handler is a closure inside setup_auth and cannot be imported, so
        this reads the source: every write to wfile in that function must go
        through _callback_page, never an f-string of its own.
        """
        import ast
        import inspect

        from fitbit_mcp import auth

        tree = ast.parse(inspect.getsource(auth.setup_auth))
        writes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "write"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "wfile"
        ]
        assert writes, "no wfile.write found - has the callback handler moved?"
        for call in writes:
            source = ast.unparse(call)
            assert "_callback_page(" in source, f"unescaped page built at: {source}"

    def test_an_ordinary_message_still_reads_normally(self):
        from fitbit_mcp.auth import _callback_page

        assert "Authorised! You can close this tab." in _callback_page(
            "Authorised! You can close this tab."
        )

    def test_the_exception_reaches_the_user_only_as_its_type(self):
        """A whitelist, not a list of banned shapes.

        The page and stderr both carry what setup_auth formats, and the
        exception's own text is a filesystem path for a TLS failure and
        response bytes for a decode failure. Any expression form can carry
        it - a call argument, a concatenation, e.args[0], a walrus - so
        listing the ones seen so far only ever closes the last instance.
        The bound name is permitted inside type(e).__name__ and nowhere else.

        Deliberately strict about `raise X from e`: nothing here is meant to
        escape to the user's terminal as a chained traceback.
        """
        import ast
        import inspect

        from fitbit_mcp import auth

        tree = ast.parse(inspect.getsource(auth.setup_auth))
        offenders = []
        for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)):
            if not handler.name:
                continue
            allowed = {
                id(node.value.args[0])
                for node in ast.walk(handler)
                if isinstance(node, ast.Attribute)
                and node.attr == "__name__"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "type"
                and len(node.value.args) == 1
            }
            offenders += [
                ast.unparse(node)
                for node in ast.walk(handler)
                if isinstance(node, ast.Name)
                and node.id == handler.name
                and id(node) not in allowed
            ]
        assert not offenders, f"exception used outside type(e).__name__: {offenders}"

    def test_the_live_exception_is_not_reached_without_binding_it(self):
        """The rule above keys on the bound name, so these bypass it entirely.

        `traceback.format_exc()` is the realistic one - it is what gets added
        while debugging a failing authorisation, and it prints source lines
        and absolute paths. Unlike the ways of stringifying an object, the
        ways of reaching the live exception without naming it are a closed
        set, so naming them is not the trap the blocklist was.
        """
        import ast
        import inspect

        from fitbit_mcp import auth

        tree = ast.parse(inspect.getsource(auth.setup_auth))

        unbound = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler) and not node.name
        ]
        assert not unbound, (
            f"except clause binds no name, so the rule above is blind to it: {unbound}"
        )

        # Exact callables for sys, whose exit() this function uses legitimately;
        # whole modules for traceback and inspect, which it has no other use for.
        banned_calls = {"sys.exc_info", "sys.exception", "exc_info", "locals", "vars"}
        banned_modules = {"traceback", "inspect"}
        reached = sorted(
            {
                name
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                for name in [ast.unparse(node.func)]
                if name in banned_calls or name.split(".")[0] in banned_modules
            }
        )
        assert not reached, f"reaches the live exception without binding it: {reached}"
