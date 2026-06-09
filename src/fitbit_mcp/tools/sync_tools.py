"""Sync tool: fetch data from Fitbit API and store in local SQLite cache."""

import logging
import time
from datetime import date, timedelta

import anyio

from .. import api, config, db
from ..config import (
    AZM_MAX_RANGE_DAYS,
    BREATHING_RATE_MAX_RANGE_DAYS,
    CARDIO_FITNESS_MAX_RANGE_DAYS,
    HRV_MAX_RANGE_DAYS,
    MAX_RANGE_DAYS,
    SKIN_TEMPERATURE_MAX_RANGE_DAYS,
    SLEEP_MAX_RANGE_DAYS,
    SPO2_MAX_RANGE_DAYS,
    WEIGHT_MAX_RANGE_DAYS,
)
from ..helpers import format_response, require_auth
from ..mcp_instance import mcp

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
                conn,
                ds,
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
        db.save_activity(
            conn,
            {
                "date": d.isoformat(),
                "steps": summary.get("steps"),
                "calories_out": summary.get("caloriesOut"),
                "active_minutes": (
                    (summary.get("veryActiveMinutes") or 0)
                    + (summary.get("fairlyActiveMinutes") or 0)
                ),
                "very_active_minutes": summary.get("veryActiveMinutes"),
                "fairly_active_minutes": summary.get("fairlyActiveMinutes"),
                "lightly_active_minutes": summary.get("lightlyActiveMinutes"),
                "sedentary_minutes": summary.get("sedentaryMinutes"),
                "floors": summary.get("floors"),
                "distance_km": distance_km,
            },
        )
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
            db.save_exercise(
                conn,
                log_id,
                {
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
                },
            )
            count += 1

        conn.commit()
        if past_end:
            break
        last_date = activities[-1].get("startTime", "")[:10]
        if last_date <= after_date:
            break
        after_date = last_date

    return count


def aggregate_sleep_nights(entries: list[dict]) -> list[dict]:
    """Collapse raw Fitbit sleep sessions into one row per night.

    Fitbit returns one entry per sleep *session*. A fragmented or split
    night - a main sleep plus a nap, or a wake-and-resume that Fitbit logs
    as two records - yields several entries sharing the same `dateOfSleep`.
    The cache is keyed by date, so without aggregation the last session
    written silently overwrites the rest, leaving a misleadingly short
    night. Here we sum the sessions into the night's true total, matching
    Fitbit's own per-day `summary.totalMinutesAsleep`.

    Aggregation rules per `dateOfSleep`:
      - total_minutes / stage minutes: summed across all sessions
      - start_time: earliest; end_time: latest
      - efficiency: time-in-bed-weighted mean of sessions that report one
        (so a single-session night keeps Fitbit's reported value exactly)
      - sessions: count of source records (1 = normal night)

    Entries without a `dateOfSleep` are skipped.
    """
    _STAGE_COLS = (
        ("deep", "deep_minutes"),
        ("light", "light_minutes"),
        ("rem", "rem_minutes"),
        ("wake", "wake_minutes"),
    )
    nights: dict[str, dict] = {}
    for entry in entries:
        ds = entry.get("dateOfSleep")
        if not ds:
            continue
        stages = (entry.get("levels") or {}).get("summary") or {}
        asleep = entry.get("minutesAsleep") or 0
        in_bed = entry.get("timeInBed") or 0
        eff = entry.get("efficiency")
        start = entry.get("startTime")
        end = entry.get("endTime")

        acc = nights.get(ds)
        if acc is None:
            acc = {
                "date": ds,
                "sessions": 0,
                "total_minutes": 0,
                "start_time": start,
                "end_time": end,
                "deep_minutes": None,
                "light_minutes": None,
                "rem_minutes": None,
                "wake_minutes": None,
                "_eff_weighted": 0.0,
                "_eff_in_bed": 0,
            }
            nights[ds] = acc

        acc["sessions"] += 1
        acc["total_minutes"] += asleep
        if start and (acc["start_time"] is None or start < acc["start_time"]):
            acc["start_time"] = start
        if end and (acc["end_time"] is None or end > acc["end_time"]):
            acc["end_time"] = end
        for stage_key, col in _STAGE_COLS:
            minutes = (stages.get(stage_key) or {}).get("minutes")
            if minutes is not None:
                acc[col] = (acc[col] or 0) + minutes
        if eff is not None and in_bed:
            acc["_eff_weighted"] += eff * in_bed
            acc["_eff_in_bed"] += in_bed

    rows = []
    for acc in nights.values():
        in_bed = acc.pop("_eff_in_bed")
        weighted = acc.pop("_eff_weighted")
        acc["efficiency"] = round(weighted / in_bed) if in_bed else None
        rows.append(acc)
    return sorted(rows, key=lambda r: r["date"])


def _sync_sleep(conn, start_date: date, end_date: date) -> int:
    """Sync sleep logs. Returns count of nights upserted.

    Multiple same-night sessions are aggregated into one row per night via
    `aggregate_sleep_nights`, so a fragmented night is stored as its true
    total rather than collapsing to the last session written.
    """
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(start_date, end_date, SLEEP_MAX_RANGE_DAYS):
        path = f"/1.2/user/-/sleep/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        for row in aggregate_sleep_nights(data.get("sleep", [])):
            db.save_sleep(conn, row)
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
                db.save_weight(
                    conn,
                    {
                        "date": ds,
                        "weight_kg": entry.get("weight"),
                        "bmi": entry.get("bmi"),
                        "fat_pct": entry.get("fat"),
                    },
                )
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
            db.save_spo2(
                conn,
                {
                    "date": ds,
                    "avg": entry["value"].get("avg"),
                    "min": entry["value"].get("min"),
                    "max": entry["value"].get("max"),
                },
            )
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
                db.save_hrv(
                    conn,
                    {
                        "date": ds,
                        "daily_rmssd": entry["value"].get("dailyRmssd"),
                        "deep_rmssd": entry["value"].get("deepRmssd"),
                    },
                )
                count += 1
        conn.commit()
    return count


def _sync_azm(conn, start_date: date, end_date: date) -> int:
    """Sync daily Active Zone Minutes (zone breakdown)."""
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(start_date, end_date, AZM_MAX_RANGE_DAYS):
        path = f"/1/user/-/activities/active-zone-minutes/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("activities-active-zone-minutes", []):
            ds = entry.get("dateTime")
            value = entry.get("value", {}) or {}
            if not ds:
                continue
            db.save_azm(
                conn,
                {
                    "date": ds,
                    "total_minutes": value.get("activeZoneMinutes"),
                    "fat_burn_minutes": value.get("fatBurnActiveZoneMinutes"),
                    "cardio_minutes": value.get("cardioActiveZoneMinutes"),
                    "peak_minutes": value.get("peakActiveZoneMinutes"),
                },
            )
            count += 1
        conn.commit()
    return count


def _sync_breathing_rate(conn, start_date: date, end_date: date) -> int:
    """Sync nightly breathing rate (avg breaths per minute)."""
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(
        start_date, end_date, BREATHING_RATE_MAX_RANGE_DAYS
    ):
        path = f"/1/user/-/br/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("br", []):
            ds = entry.get("dateTime")
            value = entry.get("value", {}) or {}
            if not ds:
                continue
            br = value.get("breathingRate")
            if br is None:
                continue
            db.save_breathing_rate(conn, {"date": ds, "breaths_per_min": br})
            count += 1
        conn.commit()
    return count


def _sync_skin_temperature(conn, start_date: date, end_date: date) -> int:
    """Sync nightly skin temperature variation from baseline."""
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(
        start_date, end_date, SKIN_TEMPERATURE_MAX_RANGE_DAYS
    ):
        path = f"/1/user/-/temp/skin/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("tempSkin", []):
            ds = entry.get("dateTime")
            value = entry.get("value", {}) or {}
            if not ds:
                continue
            db.save_skin_temperature(
                conn,
                {
                    "date": ds,
                    "nightly_relative": value.get("nightlyRelative"),
                    "log_type": entry.get("logType"),
                },
            )
            count += 1
        conn.commit()
    return count


def _parse_vo2_max(raw) -> tuple[float | None, float | None]:
    """Parse Fitbit's vo2Max field. May be a number or a range string like '39-43'."""
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)):
        return float(raw), float(raw)
    s = str(raw).strip()
    if "-" in s:
        try:
            lo, hi = s.split("-", 1)
            return float(lo), float(hi)
        except ValueError:
            return None, None
    try:
        v = float(s)
        return v, v
    except ValueError:
        return None, None


def _sync_cardio_fitness(conn, start_date: date, end_date: date) -> int:
    """Sync VO2 Max / Cardio Fitness Score."""
    count = 0
    for chunk_start, chunk_end in _chunk_date_ranges(
        start_date, end_date, CARDIO_FITNESS_MAX_RANGE_DAYS
    ):
        path = f"/1/user/-/cardioscore/date/{chunk_start}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("cardioScore", []):
            ds = entry.get("dateTime")
            value = entry.get("value", {}) or {}
            if not ds:
                continue
            lo, hi = _parse_vo2_max(value.get("vo2Max"))
            if lo is None and hi is None:
                continue
            db.save_cardio_fitness(
                conn,
                {
                    "date": ds,
                    "vo2_max_low": lo,
                    "vo2_max_high": hi,
                },
            )
            count += 1
        conn.commit()
    return count


def _has_food_log(data: dict) -> bool:
    """Decide whether a /foods/log/date/{d}.json response represents real activity.

    Fitbit returns `summary.calories=0` and `summary.water=0` for days with no
    log, so plain None-checks would store empty rows for every synced day. Only
    treat the day as logged if there's at least one food entry or a non-zero
    water/calorie figure.
    """
    foods = data.get("foods") or []
    if foods:
        return True
    summary = data.get("summary", {}) or {}
    return bool(summary.get("calories")) or bool(summary.get("water"))


def _sync_food_log(conn, start_date: date, end_date: date) -> int:
    """Sync daily food/water summary. One API call per day (no range endpoint).

    Skips days with no log entries to avoid filling the cache with 0/0 rows.
    """
    count = 0
    d = start_date
    while d <= end_date:
        path = f"/1/user/-/foods/log/date/{d}.json"
        try:
            data = api.get(path)
        except api.FitbitRateLimitError as e:
            logger.warning("Rate limited during food sync, sleeping %ds", e.reset_seconds)
            time.sleep(e.reset_seconds + 5)
            data = api.get(path)
        if not _has_food_log(data):
            d += timedelta(days=1)
            continue
        summary = data.get("summary", {}) or {}
        db.save_food_log(
            conn,
            {
                "date": d.isoformat(),
                "calories_in": summary.get("calories"),
                "water_ml": summary.get("water"),
            },
        )
        count += 1
        d += timedelta(days=1)
    conn.commit()
    return count


def run_sync(data_types: list[str], days: int = 30) -> dict:
    """Run sync outside MCP context (for CLI use). Returns results dict."""
    today = date.today()
    conn = db.get_db()
    results = {}

    for dtype in data_types:
        try:
            # Use the later of (most-recent row in table) and (most-recent
            # successful sync's end-date). The second matters for sparse
            # types like food_log: if the user stops logging, the data
            # table's MAX(date) freezes and we'd otherwise re-query every
            # day from then on, burning quota on confirmed-empty days.
            candidates = [
                d
                for d in (
                    db.get_last_synced_date(conn, dtype),
                    db.get_last_attempted_date(conn, dtype),
                )
                if d
            ]
            if candidates:
                start_date = date.fromisoformat(max(candidates))
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
            elif dtype == "azm":
                count = _sync_azm(conn, start_date, end_date)
            elif dtype == "breathing_rate":
                count = _sync_breathing_rate(conn, start_date, end_date)
            elif dtype == "skin_temperature":
                count = _sync_skin_temperature(conn, start_date, end_date)
            elif dtype == "cardio_fitness":
                count = _sync_cardio_fitness(conn, start_date, end_date)
            elif dtype == "food_log":
                count = _sync_food_log(conn, start_date, end_date)
            else:
                results[dtype] = {"status": "error", "message": f"Unknown type: {dtype}"}
                continue

            db.log_sync(conn, dtype, "ok", count, last_date_attempted=end_date.isoformat())
            results[dtype] = {
                "status": "ok",
                "records": count,
                "range": f"{start_date} to {end_date}",
            }

        # FitbitOfflineError is intentionally not handled like the errors
        # below: it must propagate to require_auth / the CLI sync handler so
        # offline mode returns one clean message instead of per-type error
        # rows. We only intercept it to close the connection, then re-raise.
        except api.FitbitRateLimitError as e:
            db.log_sync(conn, dtype, "partial", notes="rate limited")
            results[dtype] = {"status": "rate_limited", "message": str(e)}
        except api.FitbitAuthError as e:
            # Log an error row so a dead/expired token is visible in sync_log
            # and the CLI sync can exit non-zero.
            db.log_sync(conn, dtype, "error", notes=f"auth: {e}")
            results[dtype] = {"status": "auth_error", "message": str(e)}
        except api.FitbitAPIError as e:
            db.log_sync(conn, dtype, "error", notes=str(e))
            results[dtype] = {"status": "error", "message": str(e)}
        except api.FitbitOfflineError:
            conn.close()
            raise

    conn.close()
    return results


def auto_sync_if_stale(data_type: str) -> None:
    """Sync data_type if it has never been synced or last sync was before today.

    Failures are silently suppressed - the caller should still query the cache.
    This ensures tools work on first use without requiring an explicit fitbit_sync call.

    No-op in offline mode (FITBIT_MCP_OFFLINE): a cache-only host never syncs.
    """
    if config.OFFLINE_MODE:
        return

    conn = db.get_db()
    last_sync = db.get_last_sync_time(conn, data_type)
    conn.close()

    if last_sync is not None and last_sync.date() >= date.today():
        return

    try:
        run_sync([data_type])
    except Exception:
        logger.debug("Auto-sync failed for %s", data_type, exc_info=True)


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
            "exercises", "sleep", "weight", "spo2", "hrv", "azm",
            "breathing_rate", "skin_temperature", "cardio_fitness", "food_log".
            Comma-separated for multiple, e.g. "sleep,hrv". Default: "all".
        days: Days of history for first sync (default: 30). Ignored
            on subsequent syncs (uses last synced date).

    Returns summary of records synced per data type.
    Not for querying data - use fitbit_get_heart_rate, fitbit_get_activity,
    fitbit_get_sleep, etc. instead.
    """
    if config.OFFLINE_MODE:
        return format_response(
            {
                "error": (
                    "Offline mode is on (FITBIT_MCP_OFFLINE); syncing is disabled. "
                    "Run the sync on the host that owns the cache, or unset "
                    "FITBIT_MCP_OFFLINE."
                ),
                "offline_mode": True,
            }
        )

    types = [t.strip() for t in data_types.split(",")]
    if "all" in types:
        types = [
            "heart_rate",
            "activity",
            "exercises",
            "sleep",
            "weight",
            "spo2",
            "hrv",
            "azm",
            "breathing_rate",
            "skin_temperature",
            "cardio_fitness",
            "food_log",
        ]

    results = await anyio.to_thread.run_sync(lambda: run_sync(types, days))
    return format_response(results)
