"""Tests for the fitbit-mcp command-line entry point."""

from importlib.metadata import version
from unittest.mock import patch

import pytest

from fitbit_mcp import cli


def test_version_flag_prints_package_version(capsys):
    with patch("sys.argv", ["fitbit-mcp", "--version"]):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"fitbit-mcp {version('fitbit-mcp')}"


def test_version_flag_takes_precedence_over_subcommand(capsys):
    with patch("sys.argv", ["fitbit-mcp", "auth", "--version"]):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"fitbit-mcp {version('fitbit-mcp')}"


def test_version_flag_does_not_mask_invalid_subcommand_args(capsys):
    with patch("sys.argv", ["fitbit-mcp", "import", "--data-dir", "--version"]):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    assert f"fitbit-mcp {version('fitbit-mcp')}" not in captured.out


def test_sync_refuses_in_offline_mode(capsys, monkeypatch):
    monkeypatch.setattr("fitbit_mcp.config.OFFLINE_MODE", True)
    with patch("sys.argv", ["fitbit-mcp", "sync"]):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()

    assert exc_info.value.code == 1
    assert "FITBIT_MCP_OFFLINE" in capsys.readouterr().err
