"""Breathing rate query tool."""

from datetime import timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date
from .. import api, db
from .sync_tools import auto_sync_if_stale


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch breathing rate data directly from the API."""
    from ..config import BREATHING_RATE_MAX_RANGE_DAYS
    results = {}
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=BREATHING_RATE_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/br/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("br", []):
            ds = entry.get("dateTime")
            value = entry.get("value", {}) or {}
            br = value.get("breathingRate")
            if not ds or br is None:
                continue
            results[ds] = {"date": ds, "breaths_per_min": br}
        d = chunk_end + timedelta(days=1)
    return sorted(results.values(), key=lambda x: x["date"])


@mcp.tool()
@require_auth
async def fitbit_get_breathing_rate(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get nightly breathing rate (avg breaths per minute during sleep).

    Sourced during sleep tracking. Useful as an illness/recovery signal:
    sustained increases of 2-3 bpm above personal baseline can indicate
    incipient infection or strain. Returns from cache by default,
    auto-syncing if stale.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per night with breaths_per_min.
    Typical adult range: 12-20 bpm at rest.
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("breathing_rate"))
        def _query():
            conn = db.get_db()
            rows = db.query_breathing_rate(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows
        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response({
            "message": "No breathing rate data found for this period.",
            "hint": "Try live=True to fetch directly from the API. Requires sleep tracking.",
        })

    return format_response({"breathing_rate": entries, "count": len(entries)})
