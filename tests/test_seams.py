"""Claims no input to the program can falsify.

A behavioural test asks "given this input, what happens". The assertions
here are about the code's structure and its packaging, so nothing you can
feed the server exercises them - which is why each of these survived until
someone went looking. See AGENTS.md, "Seams the suite does not cross".
"""

import ast
import tomllib
from pathlib import Path

import fitbit_mcp

_PATH_NAMES = {
    "CONFIG_DIR",
    "DB_PATH",
    "FITBIT_CONFIG_PATH",
    "FITBIT_TOKENS_PATH",
    "data_dir",
    "path",
}
_CLI_ONLY = {"cli.py", "doctor.py", "importer.py"}
_LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception", "log"}


def _shared_sources():
    root = Path(fitbit_mcp.__file__).parent
    return [p for p in sorted(root.rglob("*.py")) if p.name not in _CLI_ONLY]


def test_no_logger_call_in_shared_code_carries_a_path():
    """A CLI subcommand may print a path; shared code may not.

    Server mode writes log lines to stderr, where the MCP client collects
    them, so a log line is closer to a tool response than to a terminal.

    _PATH_NAMES is a blocklist, which is weaker than the whitelist guarding
    setup_auth. It is defensible only because the path identifiers in
    config.py are a small closed set - a new one must be added here.
    """
    offenders = []
    for source in _shared_sources():
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            # Keyed on the logging method, not on how the logger is spelled:
            # `logger.info` and `logging.getLogger(__name__).info` are the
            # same call, and matching the receiver's name misses the second.
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LOG_METHODS
            ):
                continue
            for arg in node.args + [kw.value for kw in node.keywords]:
                if any(name in ast.unparse(arg) for name in _PATH_NAMES):
                    offenders.append(f"{source.name}:{node.lineno} {ast.unparse(node)}")
    assert not offenders, f"log line carries a path: {offenders}"


def test_the_declared_version_and_the_lockfile_agree():
    """Nothing behavioural can see a lockfile left behind by a bump.

    A release does both by hand, and a commit exists in this history
    because one of them was missed.
    """
    root = Path(fitbit_mcp.__file__).parents[2]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    locked = tomllib.loads((root / "uv.lock").read_text())
    ours = [p for p in locked["package"] if p["name"] == "fitbit-mcp"]
    assert ours, "fitbit-mcp is not in uv.lock"
    assert ours[0]["version"] == declared, (
        f"pyproject.toml says {declared}, uv.lock says {ours[0]['version']} - run `uv lock`"
    )
