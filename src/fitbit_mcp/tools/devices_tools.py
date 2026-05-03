"""Fitbit device list query tool (live only - no caching)."""

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth
from .. import api


def _fetch_devices() -> list[dict]:
    """Fetch the list of paired Fitbit devices. Endpoint returns a bare JSON array."""
    data = api.get("/1/user/-/devices.json")
    if not isinstance(data, list):
        return []
    devices = []
    for entry in data:
        devices.append({
            "id": entry.get("id"),
            "type": entry.get("type"),
            "device_version": entry.get("deviceVersion"),
            "battery": entry.get("battery"),
            "battery_level": entry.get("batteryLevel"),
            "last_sync_time": entry.get("lastSyncTime"),
            "mac": entry.get("mac"),
            "features": entry.get("features", []),
        })
    return devices


@mcp.tool()
@require_auth
async def fitbit_get_devices() -> str:
    """List paired Fitbit devices with battery level and last sync time.

    Live-only (no caching) - reflects current device state. Useful for
    monitoring tracker health, knowing which device produced data, and
    spotting sync gaps.

    Returns one entry per paired device with id, type, device_version,
    battery (e.g. "High"), battery_level (0-100), last_sync_time, mac,
    and features list.
    """
    devices = await anyio.to_thread.run_sync(_fetch_devices)
    if not devices:
        return format_response({"message": "No devices found.", "devices": []})
    return format_response({"devices": devices, "count": len(devices)})
