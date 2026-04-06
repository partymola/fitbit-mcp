"""Sync tool: fetch data from Fitbit API and store in local SQLite cache."""

import logging
import time
from datetime import date, timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth
from .. import api, db
from ..config import (
    MAX_RANGE_DAYS, SLEEP_MAX_RANGE_DAYS,
    WEIGHT_MAX_RANGE_DAYS, SPO2_MAX_RANGE_DAYS, HRV_MAX_RANGE_DAYS,
)

logger = logging.getLogger(__name__)


def _chunk_date_ranges(start_date: date, end_date: date, max_days: int) -> list[tuple[date, date]]:
    """Split a date range into chunks of max_days."""
    ranges = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=max_days - 1), end_date)
        ranges.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return ranges


def _sync_heart_rate(conn, start_date: date, end_date: date) -> int:
    """Sync resting HR and HR zones. Returns count of records upserted."""
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(start_date, end_date, MAX_RANGE_DAYS):
        path = f"/1/user/-/activities/heart/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("activities-heart", []):
            ds = entry["dateTime"]
            value = entry.get("value", {})
            db.save_heart_rate(
                conn, ds,
                value.get("restingHeartRate"),
                value.get("heartRateZones", []),
            )
            count += 1
        conn.commit()
    return count


def _sync_activity(conn, start_date: date, end_date: date) -> int:
    """Sync daily activity summaries. Fetched per day (no date-range endpoint).

    Warning: uses 1 API call per day. A 30-day sync consumes 30 of the
    150 requests/hour quota. Rate-limited retries sleep synchronously.
    """
    count = 0
    d = start_date
    while d <= end_date:
        path = f"/1/user/-/activities/date/{d}.json"
        try:
            data = api.get(path)
        except api.FitbitRateLimitError as e:
            logger.warning("Rate limited during activity sync, sleeping %ds", e.reset_seconds)
            time.sleep(e.reset_seconds + 5)
            data = api.get(path)
        summary = data.get("summary", {})
        distances = summary.get("distances", [{}])
        distance_km = distances[0].get("distance") if distances else None
        db.save_activity(conn, {
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
        count += 1
        d += timedelta(days=1)
    conn.commit()
    return count


def _sync_exercises(conn, start_date: date, end_date: date) -> int:
    """Sync exercise log via the activity list endpoint (paginated)."""
    count = 0
    after_date = start_date.isoformat()

    while True:
        path = f"/1/user/-/activities/list.json?afterDate={after_date}&sort=asc&offset=0&limit=100"
        data = api.get(path)
        activities = data.get("activities", [])
        if not activities:
            break

        past_end = False
        for entry in activities:
            log_date = entry.get("startTime", "")[:10]
            if log_date > end_date.isoformat():
                past_end = True
                break
            log_id = str(entry.get("logId", ""))
            db.save_exercise(conn, log_id, {
                "date": log_date,
                "name": entry.get("activityName"),
                "duration_min": (entry.get("activeDuration") or 0) // 60000,
                "calories": entry.get("calories"),
                "avg_hr": entry.get("averageHeartRate"),
                "steps": entry.get("steps"),
                "distance_km": entry.get("distance"),
                "distance_unit": entry.get("distanceUnit"),
                "start_time": entry.get("startTime"),
                "source": (entry.get("source") or {}).get("name"),
                "log_type": entry.get("logType"),
            })
            count += 1

        conn.commit()
        if past_end:
            break
        last_date = activities[-1].get("startTime", "")[:10]
        if last_date <= after_date:
            break
        after_date = last_date

    return count


def _sync_sleep(conn, start_date: date, end_date: date) -> int:
    """Sync sleep logs."""
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(start_date, end_date, SLEEP_MAX_RANGE_DAYS):
        path = f"/1.2/user/-/sleep/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("sleep", []):
            ds = entry.get("dateOfSleep")
            if not ds:
                continue
            stages = entry.get("levels", {}).get("summary", {})
            db.save_sleep(conn, {
                "date": ds,
                "total_minutes": entry.get("minutesAsleep"),
                "efficiency": entry.get("efficiency"),
                "start_time": entry.get("startTime"),
                "end_time": entry.get("endTime"),
                "deep_minutes": (stages.get("deep") or {}).get("minutes"),
                "light_minutes": (stages.get("light") or {}).get("minutes"),
                "rem_minutes": (stages.get("rem") or {}).get("minutes"),
                "wake_minutes": (stages.get("wake") or {}).get("minutes"),
            })
            count += 1
        conn.commit()
    return count


def _sync_weight(conn, start_date: date, end_date: date) -> int:
    """Sync weight logs."""
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(start_date, end_date, WEIGHT_MAX_RANGE_DAYS):
        path = f"/1/user/-/body/log/weight/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("weight", []):
            ds = entry.get("date")
            if ds:
                db.save_weight(conn, {
                    "date": ds,
                    "weight_kg": entry.get("weight"),
                    "bmi": entry.get("bmi"),
                    "fat_pct": entry.get("fat"),
                })
                count += 1
        conn.commit()
    return count


def _sync_spo2(conn, start_date: date, end_date: date) -> int:
    """Sync nightly SpO2 data."""
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(start_date, end_date, SPO2_MAX_RANGE_DAYS):
        path = f"/1/user/-/spo2/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        # API may return a list, a single dict, or {} (no data). Normalise to list.
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            ds = entry.get("dateTime")
            if not ds or "value" not in entry:
                # Empty response ({}) or missing data - skip
                continue
            db.save_spo2(conn, {
                "date": ds,
                "avg": entry["value"].get("avg"),
                "min": entry["value"].get("min"),
                "max": entry["value"].get("max"),
            })
            count += 1
        conn.commit()
    return count


def _sync_hrv(conn, start_date: date, end_date: date) -> int:
    """Sync nightly HRV data."""
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(start_date, end_date, HRV_MAX_RANGE_DAYS):
        path = f"/1/user/-/hrv/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("hrv", []):
            ds = entry.get("dateTime")
            if ds and "value" in entry:
                db.save_hrv(conn, {
                    "date": ds,
                    "daily_rmssd": entry["value"].get("dailyRmssd"),
                    "deep_rmssd": entry["value"].get("deepRmssd"),
                })
                count += 1
        conn.commit()
    return count


def run_sync(data_types: list[str], days: int = 30) -> dict:
    """Run sync outside MCP context (for CLI use). Returns results dict."""
    today = date.today()
    conn = db.get_db()
    results = {}

    for dtype in data_types:
        try:
            last_date = db.get_last_synced_date(conn, dtype)
            if last_date:
                start_date = date.fromisoformat(last_date)
            else:
                start_date = today - timedelta(days=days)
            end_date = today

            if dtype == "heart_rate":
                count = _sync_heart_rate(conn, start_date, end_date)
            elif dtype == "activity":
                count = _sync_activity(conn, start_date, end_date)
            elif dtype == "exercises":
                count = _sync_exercises(conn, start_date, end_date)
            elif dtype == "sleep":
                count = _sync_sleep(conn, start_date, end_date)
            elif dtype == "weight":
                count = _sync_weight(conn, start_date, end_date)
            elif dtype == "spo2":
                count = _sync_spo2(conn, start_date, end_date)
            elif dtype == "hrv":
                count = _sync_hrv(conn, start_date, end_date)
            else:
                results[dtype] = {"status": "error", "message": f"Unknown type: {dtype}"}
                continue

            db.log_sync(conn, dtype, "ok", count)
            results[dtype] = {
                "status": "ok",
                "records": count,
                "range": f"{start_date} to {end_date}",
            }

        except api.FitbitRateLimitError as e:
            db.log_sync(conn, dtype, "partial", notes="rate limited")
            results[dtype] = {"status": "rate_limited", "message": str(e)}
        except api.FitbitAuthError as e:
            results[dtype] = {"status": "auth_error", "message": str(e)}
        except api.FitbitAPIError as e:
            db.log_sync(conn, dtype, "error", notes=str(e))
            results[dtype] = {"status": "error", "message": str(e)}

    conn.close()
    return results


@mcp.tool()
@require_auth
async def fitbit_sync(
    data_types: str = "all",
    days: int = 30,
) -> str:
    """Sync Fitbit health data to the local cache.

    Fetches data from the Fitbit API and stores it in SQLite for fast
    offline queries. Run this before using other fitbit_get_* tools.

    Syncs incrementally: only fetches data newer than the most recent
    entry in each table. First sync fetches the specified number of days.

    Args:
        data_types: What to sync. Options: "all", "heart_rate", "activity",
            "exercises", "sleep", "weight", "spo2", "hrv".
            Comma-separated for multiple, e.g. "sleep,hrv". Default: "all".
        days: Days of history for first sync (default: 30). Ignored
            on subsequent syncs (uses last synced date).

    Returns summary of records synced per data type.
    Not for querying data - use fitbit_get_heart_rate, fitbit_get_activity,
    fitbit_get_sleep, etc. instead.
    """
    types = [t.strip() for t in data_types.split(",")]
    if "all" in types:
        types = ["heart_rate", "activity", "exercises", "sleep", "weight", "spo2", "hrv"]

    results = await anyio.to_thread.run_sync(lambda: run_sync(types, days))
    return format_response(results)
