"""Control hierarchy stubs."""

from typing import Any


def get_controller_status_stub() -> dict[str, Any]:
    """Return status stub for control systems."""
    return {
        "bms_status": "STANDBY",
        "ppc_mode": "MANUAL",
        "ems_mode": "IDLE",
        "message": "Control logic implementation pending WP02+",
    }
