"""Daily activity query tool."""

from datetime import timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date
from .. import api, db


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch daily activity summaries directly from the API."""
    results = []
    d = start_date
    while d <= end_date:
        path = f"/1/user/-/activities/date/{d}.json"
        data = api.get(path)
        summary = data.get("summary", {})
        distances = summary.get("distances", [{}])
        distance_km = distances[0].get("distance") if distances else None
        results.append({
            "date": d.isoformat(),
            "steps": summary.get("steps"),
            "calories_out": summary.get("caloriesOut"),
            "active_minutes": (
                (summary.get("veryActiveMinutes") or 0) +
                (summary.get("fairlyActiveMinutes") or 0)
            ),
            "very_active_minutes": summary.get("veryActiveMinutes"),
            "fairly_active_minutes": summary.get("fairlyActiveMinutes"),
            "lightly_active_minutes": summary.get("lightlyActiveMinutes"),
            "sedentary_minutes": summary.get("sedentaryMinutes"),
            "floors": summary.get("floors"),
            "distance_km": distance_km,
        })
        d += timedelta(days=1)
    return results


@mcp.tool()
@require_auth
async def fitbit_get_activity(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get daily activity summaries (steps, calories, active minutes, distance).

    Returns data from the local cache by default. Use live=True to fetch
    from Fitbit API. Run fitbit_sync first to populate the cache.

    Note: live=True fetches one API call per day - avoid large ranges to
    stay within the 150 requests/hour rate limit.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per day with steps, calories, active minutes, distance.
    active_minutes = very_active + fairly_active (excludes lightly active).
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        def _query():
            conn = db.get_db()
            rows = db.query_activity(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows
        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response({
            "message": "No activity data found for this period.",
            "hint": "Run fitbit_sync first, or try live=True.",
        })

    return format_response({"activity": entries, "count": len(entries)})
