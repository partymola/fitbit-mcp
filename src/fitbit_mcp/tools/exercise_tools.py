"""Exercise log query tool."""

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date
from .. import api, db
from .sync_tools import auto_sync_if_stale


def _fetch_live(start_date, end_date, exercise_type: str | None) -> list[dict]:
    """Fetch exercise log directly from the API."""
    results = []
    after_date = start_date.isoformat()

    while True:
        path = f"/1/user/-/activities/list.json?afterDate={after_date}&sort=asc&offset=0&limit=100"
        data = api.get(path)
        activities = data.get("activities", [])
        if not activities:
            break

        done = False
        for entry in activities:
            log_date = entry.get("startTime", "")[:10]
            if log_date > end_date.isoformat():
                done = True
                break
            name = entry.get("activityName", "")
            if exercise_type and exercise_type.lower() not in name.lower():
                continue
            results.append({
                "date": log_date,
                "name": name,
                "duration_min": (entry.get("activeDuration") or 0) // 60000,
                "calories": entry.get("calories"),
                "avg_hr": entry.get("averageHeartRate"),
                "steps": entry.get("steps"),
                "distance_km": entry.get("distance"),
                "start_time": entry.get("startTime"),
                "source": (entry.get("source") or {}).get("name"),
                "log_type": entry.get("logType"),
            })

        if done:
            break
        last_date = activities[-1].get("startTime", "")[:10]
        if last_date <= after_date:
            break
        after_date = last_date

    return results


@mcp.tool()
@require_auth
async def fitbit_get_exercises(
    start_date: str | None = None,
    end_date: str | None = None,
    exercise_type: str | None = None,
    live: bool = False,
) -> str:
    """Get exercise log entries (individual tracked activities).

    Returns exercise sessions from the local cache by default. Use live=True
    to fetch from Fitbit API. Run fitbit_sync first to populate the cache.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        exercise_type: Filter by activity name (case-insensitive substring match),
            e.g. "cycling", "walk", "run". Default: all types.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns exercise entries with name, duration, calories, avg heart rate,
    distance, and source (auto-detect vs manual).
    Note: HR data from cycling may be unreliable (optical sensor vs handlebar grip).
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end, exercise_type))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("exercises"))
        def _query():
            conn = db.get_db()
            rows = db.query_exercises(conn, start.isoformat(), end.isoformat(), exercise_type)
            conn.close()
            return rows
        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response({
            "message": "No exercise entries found for this period.",
            "hint": "Try live=True to fetch directly from the API.",
        })

    return format_response({"exercises": entries, "count": len(entries)})
