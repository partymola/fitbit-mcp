"""Skin temperature query tool."""

from datetime import timedelta

import anyio

from .. import api, db
from ..helpers import format_response, parse_date, require_auth
from ..mcp_instance import mcp
from .sync_tools import auto_sync_if_stale


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch skin temperature data directly from the API."""
    from ..config import SKIN_TEMPERATURE_MAX_RANGE_DAYS

    results = {}
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=SKIN_TEMPERATURE_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/temp/skin/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("tempSkin", []):
            ds = entry.get("dateTime")
            value = entry.get("value", {}) or {}
            if not ds:
                continue
            results[ds] = {
                "date": ds,
                "nightly_relative": value.get("nightlyRelative"),
                "log_type": entry.get("logType"),
            }
        d = chunk_end + timedelta(days=1)
    return sorted(results.values(), key=lambda x: x["date"])


@mcp.tool()
@require_auth
async def fitbit_get_temperature(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get nightly skin temperature variation (degrees Celsius from personal baseline).

    Recorded during sleep. Returns the relative deviation, not absolute temperature -
    Fitbit needs ~3 nights to establish baseline before values appear.
    Useful as an illness/cycle/recovery signal.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per night with nightly_relative (degrees C, can be negative)
    and log_type (e.g. "dermal").
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("skin_temperature"))

        def _query():
            conn = db.get_db()
            rows = db.query_skin_temperature(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows

        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response(
            {
                "message": "No skin temperature data found for this period.",
                "hint": (
                    "Try live=True to fetch directly from the API. "
                    "Requires sleep tracking and baseline."
                ),
            }
        )

    return format_response({"skin_temperature": entries, "count": len(entries)})
