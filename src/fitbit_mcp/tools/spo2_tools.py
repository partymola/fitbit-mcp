"""SpO2 (blood oxygen saturation) query tool."""

from datetime import timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date
from .. import api, db


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch SpO2 data directly from the API."""
    from ..config import SPO2_MAX_RANGE_DAYS
    results = {}
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=SPO2_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/spo2/date/{d}/{chunk_end}.json"
        data = api.get(path)
        # API may return a list, a single dict, or {} (no data). Normalise to list.
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            ds = entry.get("dateTime")
            if not ds or "value" not in entry:
                # Empty response ({}) or missing data - skip
                continue
            results[ds] = {
                "date": ds,
                "avg": entry["value"].get("avg"),
                "min": entry["value"].get("min"),
                "max": entry["value"].get("max"),
            }
        d = chunk_end + timedelta(days=1)
    return sorted(results.values(), key=lambda x: x["date"])


@mcp.tool()
@require_auth
async def fitbit_get_spo2(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get nightly SpO2 (blood oxygen saturation) data.

    Returns data from the local cache by default. Use live=True to fetch
    from Fitbit API. Run fitbit_sync first to populate the cache.

    SpO2 data is sparse: only nights with on-wrist sleep tracking produce readings.
    Requires Fitbit Premium for access to this endpoint.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per night with avg, min, max SpO2 percentage.
    Normal range: 95-100%. Below 90% may indicate sleep apnea.
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        def _query():
            conn = db.get_db()
            rows = db.query_spo2(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows
        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response({
            "message": "No SpO2 data found for this period.",
            "hint": "Run fitbit_sync first, or try live=True.",
        })

    return format_response({"spo2": entries, "count": len(entries)})
