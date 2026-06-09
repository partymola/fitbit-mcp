"""Fitbit MCP server entry point.

Usage:
    fitbit-mcp                Start the MCP server (stdio transport)
    fitbit-mcp -V, --version  Print the installed package version
    fitbit-mcp auth           Interactive OAuth setup
    fitbit-mcp sync           Run data sync (for cron/systemd use)
    fitbit-mcp import         Import existing JSON data files into SQLite
"""

import logging
import sys
from importlib.metadata import version

# Configure logging to stderr (stdout is reserved for JSON-RPC on stdio)
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
    stream=sys.stderr,
)

# Import MCP instance and register all tools
from .mcp_instance import mcp  # noqa: E402
from .tools import (  # noqa: E402
    activity_tools,  # noqa: E402, F401
    analysis_tools,  # noqa: E402, F401
    azm_tools,  # noqa: E402, F401
    breathing_rate_tools,  # noqa: E402, F401
    cardio_fitness_tools,  # noqa: E402, F401
    devices_tools,  # noqa: E402, F401
    exercise_tools,  # noqa: E402, F401
    food_tools,  # noqa: E402, F401
    heart_tools,  # noqa: E402, F401
    hrv_tools,  # noqa: E402, F401
    lifetime_stats_tools,  # noqa: E402, F401
    sleep_tools,  # noqa: E402, F401
    spo2_tools,  # noqa: E402, F401
    sync_tools,  # noqa: E402, F401
    temperature_tools,  # noqa: E402, F401
    weight_tools,  # noqa: E402, F401
)


def _version_text():
    return f"fitbit-mcp {version('fitbit-mcp')}"


def _add_version_argument(parser):
    parser.add_argument("-V", "--version", action="version", version=_version_text())


def main():
    if len(sys.argv) == 1:
        # No subcommand: start MCP server on stdio
        mcp.run(transport="stdio")
        return

    import argparse

    parser = argparse.ArgumentParser(
        prog="fitbit-mcp",
        description="Fitbit MCP server - serves Fitbit data via the Model Context Protocol.",
    )
    _add_version_argument(parser)
    subparsers = parser.add_subparsers(dest="cmd", metavar="COMMAND")

    auth_parser = subparsers.add_parser("auth", help="Interactive OAuth setup")
    _add_version_argument(auth_parser)

    sync_parser = subparsers.add_parser("sync", help="Sync Fitbit data to local SQLite cache")
    _add_version_argument(sync_parser)
    sync_parser.add_argument(
        "--days", type=int, default=30, help="Days of history for first sync (default: 30)"
    )
    sync_parser.add_argument(
        "--types",
        default="all",
        help=(
            "Comma-separated data types: all, heart_rate, activity, exercises, sleep, "
            "weight, spo2, hrv, azm, breathing_rate, skin_temperature, cardio_fitness, food_log"
        ),
    )

    import_parser = subparsers.add_parser(
        "import", help="Import existing Fitbit JSON data files into SQLite"
    )
    _add_version_argument(import_parser)
    import_parser.add_argument(
        "--data-dir", required=True, help="Directory containing Fitbit JSON data files"
    )

    args = parser.parse_args()

    if args.cmd == "auth":
        from .auth import setup_auth

        setup_auth()

    elif args.cmd == "sync":
        from . import config

        if config.OFFLINE_MODE:
            print(
                "Offline mode is on (FITBIT_MCP_OFFLINE); refusing to sync. "
                "Unset FITBIT_MCP_OFFLINE to sync.",
                file=sys.stderr,
            )
            sys.exit(1)

        types = [t.strip() for t in args.types.split(",")]
        if "all" in types:
            types = [
                "heart_rate",
                "activity",
                "exercises",
                "sleep",
                "weight",
                "spo2",
                "hrv",
                "azm",
                "breathing_rate",
                "skin_temperature",
                "cardio_fitness",
                "food_log",
            ]

        print(f"Syncing: {', '.join(types)}")
        results = sync_tools.run_sync(types, args.days)
        for dtype, result in results.items():
            status = result.get("status", "?")
            if status == "ok":
                print(f"  {dtype}: {result.get('records', 0)} records ({result.get('range', '')})")
            else:
                print(f"  {dtype}: {status} - {result.get('message', '')}")

        # Exit non-zero if any type failed in a way that needs attention, so
        # systemd marks the unit failed (and any OnFailure= notifier fires).
        # rate_limited is transient and self-heals on the next run, so it is
        # not treated as a failure here.
        failed = [d for d, r in results.items() if r.get("status") in ("auth_error", "error")]
        if failed:
            print(f"Sync failed for: {', '.join(failed)}", file=sys.stderr)
            sys.exit(1)

    elif args.cmd == "import":
        from pathlib import Path

        from .importer import run_import

        run_import(Path(args.data_dir))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
