"""Grid and POI model stubs."""

from typing import Any


def get_grid_poi_stub() -> dict[str, Any]:
    """Return grid and POI status stub."""
    return {
        "poi_voltage_v": 13800.0,
        "poi_frequency_hz": 60.0,
        "grid_connected": True,
        "message": "Grid dynamics model pending WP02+",
    }
