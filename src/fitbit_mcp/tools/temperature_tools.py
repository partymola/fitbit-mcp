"""Temperature query tools (skin and core)."""

from datetime import timedelta

import anyio

from .. import api, db
from ..helpers import format_response, parse_date, require_auth
from ..mcp_instance import mcp
from .sync_tools import auto_sync_if_stale


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch skin temperature data directly from the API."""
    from ..config import SKIN_TEMPERATURE_MAX_RANGE_DAYS

    results = {}
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=SKIN_TEMPERATURE_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/temp/skin/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("tempSkin", []):
            ds = entry.get("dateTime")
            value = entry.get("value", {}) or {}
            if not ds:
                continue
            results[ds] = {
                "date": ds,
                "nightly_relative": value.get("nightlyRelative"),
                "log_type": entry.get("logType"),
            }
        d = chunk_end + timedelta(days=1)
    return sorted(results.values(), key=lambda x: x["date"])


def _fetch_live_core(start_date, end_date) -> list[dict]:
    """Fetch manually-logged core (body) temperatures directly from the API.

    Values are Celsius because api.py omits Accept-Language (Fitbit then returns
    metric units). De-duplicated on the (timestamp, value) pair, mirroring the
    cache's composite key: two distinct readings sharing one second-resolution
    timestamp are both kept, while exact repeats collapse.
    """
    from ..config import CORE_TEMPERATURE_MAX_RANGE_DAYS

    results = []
    seen = set()
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=CORE_TEMPERATURE_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/temp/core/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("tempCore", []):
            dt = entry.get("dateTime")
            value = entry.get("value")
            if not dt or value is None:
                continue
            key = (dt, value)
            if key in seen:
                continue
            seen.add(key)
            results.append({"datetime": dt, "date": dt[:10], "temp_celsius": value})
        d = chunk_end + timedelta(days=1)
    return sorted(results, key=lambda x: (x["datetime"], x["temp_celsius"]))


@mcp.tool()
@require_auth
async def fitbit_get_skin_temperature(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get nightly skin temperature variation (degrees Celsius from personal baseline).

    This is the device-derived RELATIVE deviation recorded during sleep, NOT an
    absolute body temperature - for fever / body-temperature readings use
    fitbit_get_core_temperature instead. Fitbit needs ~3 nights to establish a
    baseline before values appear. Useful as an illness/cycle/recovery signal.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per night with nightly_relative (degrees C, can be negative)
    and log_type (e.g. "dermal").
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("skin_temperature"))

        def _query():
            conn = db.get_db()
            rows = db.query_skin_temperature(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows

        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response(
            {
                "message": "No skin temperature data found for this period.",
                "hint": (
                    "Try live=True to fetch directly from the API. "
                    "Requires sleep tracking and baseline."
                ),
            }
        )

    return format_response({"skin_temperature": entries, "count": len(entries)})


@mcp.tool()
@require_auth
async def fitbit_get_core_temperature(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get manually-logged core (body) temperature readings (degrees Celsius).

    These are absolute body temperatures the user enters by hand - e.g. a
    forehead/thermometer reading saved to Fitbit - and are the right source for
    fever / body-temperature questions. They are NOT the device-derived nightly
    skin-temperature variation from fitbit_get_skin_temperature. A single day can
    hold several readings (each timestamped), useful for tracking a fever over time.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per logged reading with datetime (YYYY-MM-DDThh:mm:ss)
    and temp_celsius.
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live_core(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("core_temperature"))

        def _query():
            conn = db.get_db()
            rows = db.query_core_temperature(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows

        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response(
            {
                "message": "No core temperature data found for this period.",
                "hint": (
                    "Core temperature is only present when readings are logged "
                    "manually in the Fitbit app. Try live=True to fetch directly "
                    "from the API."
                ),
            }
        )

    return format_response({"core_temperature": entries, "count": len(entries)})
