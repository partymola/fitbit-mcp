"""Food and water log query tool."""

from datetime import timedelta

import anyio

from .. import api, db
from ..helpers import format_response, parse_date, require_auth
from ..mcp_instance import mcp
from .sync_tools import _has_food_log, auto_sync_if_stale


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch food log summaries directly from the API. One call per day.

    Days with no log are skipped (Fitbit returns 0/0 rather than null for
    unlogged days, so a plain None-check would emit empty rows).
    """
    results = []
    d = start_date
    while d <= end_date:
        path = f"/1/user/-/foods/log/date/{d}.json"
        data = api.get(path)
        if _has_food_log(data):
            summary = data.get("summary", {}) or {}
            results.append(
                {
                    "date": d.isoformat(),
                    "calories_in": summary.get("calories"),
                    "water_ml": summary.get("water"),
                }
            )
        d += timedelta(days=1)
    return results


@mcp.tool()
@require_auth
async def fitbit_get_food_log(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get daily food and water log summary.

    Returns calories consumed and water intake (in mL) per day. Only populated
    if the user logs food/water in the Fitbit app. Returns from cache by default,
    auto-syncing if stale.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API. Uses one API call per day.

    Returns one entry per day with calories_in and water_ml.
    Days with no logging are omitted.
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("food_log"))

        def _query():
            conn = db.get_db()
            rows = db.query_food_log(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows

        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response(
            {
                "message": "No food log data found for this period.",
                "hint": "User must log food/water in the Fitbit app for data to appear.",
            }
        )

    return format_response({"food_log": entries, "count": len(entries)})
