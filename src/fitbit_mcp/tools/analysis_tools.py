"""Trend analysis tool - works from local cache only."""

import re
from collections import defaultdict
from datetime import date, timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date, format_duration
from .. import db


def _get_period_key(ds: str, period: str) -> str:
    """Map a YYYY-MM-DD date string to a period bucket key."""
    year = ds[:4]
    month = int(ds[5:7])
    if period == "weekly":
        d = date.fromisoformat(ds)
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    elif period == "quarterly":
        q = (month - 1) // 3 + 1
        return f"{year}-Q{q}"
    else:  # monthly
        return ds[:7]


def _avg(values: list) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _trend_heart_rate(conn, start_date: str, end_date: str, period: str) -> dict:
    rows = db.query_heart_rate(conn, start_date, end_date)
    if not rows:
        return {"message": "No heart rate data in cache. Run fitbit_sync first."}

    buckets = defaultdict(list)
    for r in rows:
        hr = r.get("resting_hr")
        if hr is not None:
            buckets[_get_period_key(r["date"], period)].append(hr)

    periods = []
    for key in sorted(buckets.keys()):
        vals = buckets[key]
        periods.append({
            "period": key,
            "days": len(vals),
            "avg_resting_hr": _avg(vals),
            "min_resting_hr": min(vals) if vals else None,
            "max_resting_hr": max(vals) if vals else None,
        })
    return {"periods": periods, "data_type": "heart_rate", "aggregation": period}


def _trend_activity(conn, start_date: str, end_date: str, period: str) -> dict:
    rows = db.query_activity(conn, start_date, end_date)
    if not rows:
        return {"message": "No activity data in cache. Run fitbit_sync first."}

    buckets = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = _get_period_key(r["date"], period)
        for f in ["steps", "calories_out", "active_minutes", "distance_km"]:
            v = r.get(f)
            if v is not None:
                buckets[key][f].append(v)

    periods = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        dist = b.get("distance_km", [])
        periods.append({
            "period": key,
            "days": len(b.get("steps", [])),
            "avg_steps": _avg(b.get("steps", [])),
            "avg_active_minutes": _avg(b.get("active_minutes", [])),
            "total_distance_km": round(sum(dist), 1) if dist else None,
            "avg_calories_out": _avg(b.get("calories_out", [])),
        })
    return {"periods": periods, "data_type": "activity", "aggregation": period}


def _trend_sleep(conn, start_date: str, end_date: str, period: str) -> dict:
    rows = db.query_sleep(conn, start_date, end_date)
    if not rows:
        return {"message": "No sleep data in cache. Run fitbit_sync first."}

    buckets = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = _get_period_key(r["date"], period)
        for f in ["total_minutes", "efficiency", "deep_minutes", "rem_minutes"]:
            v = r.get(f)
            if v is not None:
                buckets[key][f].append(v)

    periods = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        total = b.get("total_minutes", [])
        periods.append({
            "period": key,
            "nights": len(total),
            "avg_total_sleep": format_duration(_avg(total)),
            "avg_deep_sleep": format_duration(_avg(b.get("deep_minutes", []))),
            "avg_rem_sleep": format_duration(_avg(b.get("rem_minutes", []))),
            "avg_efficiency": _avg(b.get("efficiency", [])),
        })
    return {"periods": periods, "data_type": "sleep", "aggregation": period}


def _trend_weight(conn, start_date: str, end_date: str, period: str) -> dict:
    rows = db.query_weight(conn, start_date, end_date)
    if not rows:
        return {"message": "No weight data in cache. Run fitbit_sync first."}

    buckets = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = _get_period_key(r["date"], period)
        for f in ["weight_kg", "fat_pct", "bmi"]:
            v = r.get(f)
            if v is not None:
                buckets[key][f].append(v)

    periods = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        periods.append({
            "period": key,
            "count": len(b.get("weight_kg", [])),
            "avg_weight_kg": _avg(b.get("weight_kg", [])),
            "avg_fat_pct": _avg(b.get("fat_pct", [])),
            "avg_bmi": _avg(b.get("bmi", [])),
        })
    return {"periods": periods, "data_type": "weight", "aggregation": period}


def _trend_spo2(conn, start_date: str, end_date: str, period: str) -> dict:
    rows = db.query_spo2(conn, start_date, end_date)
    if not rows:
        return {"message": "No SpO2 data in cache. Run fitbit_sync first."}

    buckets = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = _get_period_key(r["date"], period)
        for f in ["avg", "min", "max"]:
            v = r.get(f)
            if v is not None:
                buckets[key][f].append(v)

    periods = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        periods.append({
            "period": key,
            "nights": len(b.get("avg", [])),
            "avg_spo2": _avg(b.get("avg", [])),
            "min_spo2": min(b.get("min", [0])) if b.get("min") else None,
            "max_spo2": max(b.get("max", [0])) if b.get("max") else None,
        })
    return {"periods": periods, "data_type": "spo2", "aggregation": period}


def _trend_exercises(conn, start_date: str, end_date: str, period: str) -> dict:
    rows = db.query_exercises(conn, start_date, end_date)
    if not rows:
        return {"message": "No exercise data in cache. Run fitbit_sync first."}

    buckets = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = _get_period_key(r["date"], period)
        for f in ["duration_min", "calories"]:
            v = r.get(f)
            if v is not None:
                buckets[key][f].append(v)
        buckets[key]["_count"].append(1)

    periods = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        dur = b.get("duration_min", [])
        periods.append({
            "period": key,
            "sessions": len(b.get("_count", [])),
            "total_duration": format_duration(sum(dur)) if dur else None,
            "avg_duration": format_duration(_avg(dur)),
            "total_calories": sum(b.get("calories", [])) if b.get("calories") else None,
        })
    return {"periods": periods, "data_type": "exercises", "aggregation": period}


def _trend_hrv(conn, start_date: str, end_date: str, period: str) -> dict:
    rows = db.query_hrv(conn, start_date, end_date)
    if not rows:
        return {"message": "No HRV data in cache. Run fitbit_sync first."}

    buckets = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = _get_period_key(r["date"], period)
        for f in ["daily_rmssd", "deep_rmssd"]:
            v = r.get(f)
            if v is not None:
                buckets[key][f].append(v)

    periods = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        periods.append({
            "period": key,
            "nights": len(b.get("daily_rmssd", [])),
            "avg_daily_rmssd": _avg(b.get("daily_rmssd", [])),
            "avg_deep_rmssd": _avg(b.get("deep_rmssd", [])),
        })
    return {"periods": periods, "data_type": "hrv", "aggregation": period}


def _parse_compare_range(part: str) -> tuple[date, date] | None:
    today = date.today()
    m = re.match(r"last_(\d+)d", part)
    if m:
        days = int(m.group(1))
        return today - timedelta(days=days), today
    m = re.match(r"previous_(\d+)d", part)
    if m:
        days = int(m.group(1))
        return today - timedelta(days=days * 2), today - timedelta(days=days)
    if re.match(r"^\d{4}-\d{2}$", part):
        year, month = int(part[:4]), int(part[5:7])
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
        return start, end
    m = re.match(r"^(\d{4})-Q([1-4])$", part)
    if m:
        year, q = int(m.group(1)), int(m.group(2))
        start = date(year, (q - 1) * 3 + 1, 1)
        end_month = q * 3
        end = date(year + 1, 1, 1) - timedelta(days=1) if end_month == 12 else date(year, end_month + 1, 1) - timedelta(days=1)
        return start, end
    return None


def _compare_periods(conn, data_type: str, compare_str: str) -> dict:
    parts = re.split(r"\s+vs\s+", compare_str.strip(), maxsplit=1)
    if len(parts) != 2:
        return {"error": "Invalid compare format. Use: 'last_30d vs previous_30d' or '2026-03 vs 2026-02'"}

    ranges = []
    for part in parts:
        r = _parse_compare_range(part.strip())
        if r is None:
            return {"error": f"Cannot parse period '{part}'. Use: last_30d, previous_30d, 2026-03, or 2026-Q1"}
        ranges.append(r)

    query_fns = {
        "heart_rate": db.query_heart_rate,
        "activity": db.query_activity,
        "exercises": db.query_exercises,
        "sleep": db.query_sleep,
        "weight": db.query_weight,
        "spo2": db.query_spo2,
        "hrv": db.query_hrv,
    }
    query_fn = query_fns.get(data_type)
    if not query_fn:
        return {"error": f"Cannot compare data_type '{data_type}'. Use: heart_rate, activity, exercises, sleep, weight, spo2, or hrv."}

    def summarize(rows, dtype):
        if not rows:
            return {"count": 0}
        if dtype == "heart_rate":
            hrs = [r["resting_hr"] for r in rows if r.get("resting_hr")]
            return {"count": len(rows), "avg_resting_hr": _avg(hrs)}
        elif dtype == "activity":
            steps = [r["steps"] for r in rows if r.get("steps")]
            return {"count": len(rows), "avg_steps": _avg(steps)}
        elif dtype == "exercises":
            dur = [r["duration_min"] for r in rows if r.get("duration_min")]
            return {"count": len(rows), "avg_duration": format_duration(_avg(dur))}
        elif dtype == "sleep":
            mins = [r["total_minutes"] for r in rows if r.get("total_minutes")]
            return {"count": len(rows), "avg_total_sleep": format_duration(_avg(mins))}
        elif dtype == "weight":
            weights = [r["weight_kg"] for r in rows if r.get("weight_kg")]
            return {"count": len(rows), "avg_weight_kg": _avg(weights)}
        elif dtype == "spo2":
            avgs = [r["avg"] for r in rows if r.get("avg")]
            return {"count": len(rows), "avg_spo2": _avg(avgs)}
        elif dtype == "hrv":
            rmssd = [r["daily_rmssd"] for r in rows if r.get("daily_rmssd")]
            return {"count": len(rows), "avg_daily_rmssd": _avg(rmssd)}
        return {"count": len(rows)}

    period_a = query_fn(conn, ranges[0][0].isoformat(), ranges[0][1].isoformat())
    period_b = query_fn(conn, ranges[1][0].isoformat(), ranges[1][1].isoformat())
    result_a = summarize(period_a, data_type)
    result_b = summarize(period_b, data_type)
    result_a["period"] = f"{ranges[0][0]} to {ranges[0][1]}"
    result_b["period"] = f"{ranges[1][0]} to {ranges[1][1]}"
    return {"period_1": result_a, "period_2": result_b, "data_type": data_type}


@mcp.tool()
@require_auth
async def fitbit_trends(
    data_type: str = "activity",
    period: str = "monthly",
    start_date: str | None = None,
    end_date: str | None = None,
    compare: str | None = None,
) -> str:
    """Analyse trends in cached Fitbit data.

    Computes averages and totals over time from the local cache.
    Run fitbit_sync first to populate data.

    Args:
        data_type: What to analyse. Options: "heart_rate", "activity",
            "exercises", "sleep", "weight", "spo2", "hrv". Default: "activity".
        period: Aggregation period. Options: "weekly", "monthly",
            "quarterly". Default: "monthly".
        start_date: Start date as "YYYY-MM-DD" or "365d". Default: last 12 months.
        end_date: End date as "YYYY-MM-DD". Default: today.
        compare: Compare two periods. Format: "last_30d vs previous_30d",
            "2026-03 vs 2026-02", "2026-Q1 vs 2025-Q4".
            When set, period/start_date/end_date are ignored.

    Returns aggregated averages per period. For activity: steps, distance,
    active minutes. For exercises: sessions, duration, calories.
    For sleep: duration, efficiency, stage breakdown.
    For heart_rate: resting HR min/avg/max. For weight: weight, fat%, BMI.
    For spo2: avg/min/max oxygen saturation. For hrv: daily and deep RMSSD.
    Not for raw data - use fitbit_get_* tools instead.
    """
    def _analyse():
        conn = db.get_db()

        if compare:
            result = _compare_periods(conn, data_type, compare)
        else:
            start, end = parse_date(start_date, end_date, default_days=365)
            s, e = start.isoformat(), end.isoformat()

            trend_fns = {
                "heart_rate": _trend_heart_rate,
                "activity": _trend_activity,
                "exercises": _trend_exercises,
                "sleep": _trend_sleep,
                "weight": _trend_weight,
                "spo2": _trend_spo2,
                "hrv": _trend_hrv,
            }
            fn = trend_fns.get(data_type)
            if fn:
                result = fn(conn, s, e, period)
            else:
                result = {"error": f"Unknown data_type '{data_type}'. Use: heart_rate, activity, exercises, sleep, weight, spo2, or hrv."}

        conn.close()
        return result

    result = await anyio.to_thread.run_sync(_analyse)
    return format_response(result)
