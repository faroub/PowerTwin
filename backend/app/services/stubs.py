"""Service layer stubs."""

from typing import Any


def get_service_health_stub() -> dict[str, Any]:
    """Return health summary of background services."""
    return {
        "simulation_service": "READY",
        "historian_service": "READY",
        "message": "Core services initialized.",
    }
