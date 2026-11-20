"""Historian service stubs."""

from typing import Any


def get_historian_status_stub() -> dict[str, Any]:
    """Return historian engine status stub."""
    return {
        "status": "READY",
        "backend": "PostgreSQL / TimescaleDB",
        "active_records": 0,
        "message": "Historian ingestion ready.",
    }
