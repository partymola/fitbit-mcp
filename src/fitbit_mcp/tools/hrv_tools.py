"""HRV (heart rate variability) query tool."""

from datetime import timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date
from .. import api, db


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch HRV data directly from the API."""
    from ..config import HRV_MAX_RANGE_DAYS
    results = {}
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=HRV_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/hrv/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("hrv", []):
            ds = entry.get("dateTime")
            if ds and "value" in entry:
                results[ds] = {
                    "date": ds,
                    "daily_rmssd": entry["value"].get("dailyRmssd"),
                    "deep_rmssd": entry["value"].get("deepRmssd"),
                }
        d = chunk_end + timedelta(days=1)
    return sorted(results.values(), key=lambda x: x["date"])


@mcp.tool()
@require_auth
async def fitbit_get_hrv(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get nightly HRV (heart rate variability) data.

    Returns data from the local cache by default. Use live=True to fetch
    from Fitbit API. Run fitbit_sync first to populate the cache.

    HRV data is sparse: only nights with on-wrist sleep tracking produce readings.
    Requires Fitbit Premium for access to this endpoint.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per night with daily_rmssd and deep_rmssd (ms).
    RMSSD = root mean square of successive RR interval differences.
    Higher values generally indicate better recovery and parasympathetic activity.
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        def _query():
            conn = db.get_db()
            rows = db.query_hrv(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows
        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response({
            "message": "No HRV data found for this period.",
            "hint": "Run fitbit_sync first, or try live=True.",
        })

    return format_response({"hrv": entries, "count": len(entries)})
