"""Sleep data query tool."""

from datetime import timedelta

import anyio

from .. import api, db
from ..helpers import format_response, parse_date, require_auth
from ..mcp_instance import mcp
from .sync_tools import aggregate_sleep_nights, auto_sync_if_stale


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch sleep data directly from the API.

    Same-night sessions are aggregated into one row per night (see
    `aggregate_sleep_nights`) so live results match the cached shape and a
    fragmented night reports its true total rather than a single session.
    """
    from ..config import SLEEP_MAX_RANGE_DAYS

    entries: list[dict] = []
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=SLEEP_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1.2/user/-/sleep/date/{d}/{chunk_end}.json"
        data = api.get(path)
        entries.extend(data.get("sleep", []))
        d = chunk_end + timedelta(days=1)
    return aggregate_sleep_nights(entries)


@mcp.tool()
@require_auth
async def fitbit_get_sleep(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get nightly sleep data (duration, stages, efficiency).

    Returns sleep data from the local cache by default. Use live=True
    to fetch from Fitbit API. Run fitbit_sync first to populate the cache.

    Sleep data is sparse: only nights with watch-tracked sleep are present.
    Travel, off-wrist nights, or manual logs may be missing.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per night with total_minutes, efficiency, start/end times,
    and stage breakdown (deep, light, REM, wake minutes).
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("sleep"))

        def _query():
            conn = db.get_db()
            rows = db.query_sleep(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows

        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response(
            {
                "message": "No sleep data found for this period.",
                "hint": "Try live=True to fetch directly from the API.",
            }
        )

    return format_response({"sleep": entries, "count": len(entries)})
