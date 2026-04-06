"""Fitbit MCP server entry point.

Usage:
    fitbit-mcp                Start the MCP server (stdio transport)
    fitbit-mcp auth           Interactive OAuth setup
    fitbit-mcp sync           Run data sync (for cron/systemd use)
    fitbit-mcp import         Import existing JSON data files into SQLite
"""

import logging
import sys

# Configure logging to stderr (stdout is reserved for JSON-RPC on stdio)
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
    stream=sys.stderr,
)

# Import MCP instance and register all tools
from .mcp_instance import mcp  # noqa: E402
from .tools import sync_tools  # noqa: E402, F401
from .tools import heart_tools  # noqa: E402, F401
from .tools import activity_tools  # noqa: E402, F401
from .tools import exercise_tools  # noqa: E402, F401
from .tools import sleep_tools  # noqa: E402, F401
from .tools import weight_tools  # noqa: E402, F401
from .tools import spo2_tools  # noqa: E402, F401
from .tools import hrv_tools  # noqa: E402, F401
from .tools import analysis_tools  # noqa: E402, F401


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
    subparsers = parser.add_subparsers(dest="cmd", metavar="COMMAND")

    subparsers.add_parser("auth", help="Interactive OAuth setup")

    sync_parser = subparsers.add_parser("sync", help="Sync Fitbit data to local SQLite cache")
    sync_parser.add_argument("--days", type=int, default=30, help="Days of history for first sync (default: 30)")
    sync_parser.add_argument(
        "--types", default="all",
        help="Comma-separated data types: all, heart_rate, activity, exercises, sleep, weight, spo2, hrv",
    )

    import_parser = subparsers.add_parser("import", help="Import existing Fitbit JSON data files into SQLite")
    import_parser.add_argument("--data-dir", required=True, help="Directory containing Fitbit JSON data files")

    args = parser.parse_args()

    if args.cmd == "auth":
        from .auth import setup_auth
        setup_auth()

    elif args.cmd == "sync":
        types = [t.strip() for t in args.types.split(",")]
        if "all" in types:
            types = ["heart_rate", "activity", "exercises", "sleep", "weight", "spo2", "hrv"]

        print(f"Syncing: {', '.join(types)}")
        results = sync_tools.run_sync(types, args.days)
        for dtype, result in results.items():
            status = result.get("status", "?")
            if status == "ok":
                print(f"  {dtype}: {result.get('records', 0)} records ({result.get('range', '')})")
            else:
                print(f"  {dtype}: {status} - {result.get('message', '')}")

    elif args.cmd == "import":
        from pathlib import Path
        from .importer import run_import
        run_import(Path(args.data_dir))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
