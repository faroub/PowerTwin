"""Equipment domain stubs."""

from typing import Any


def get_equipment_summary_stub() -> dict[str, Any]:
    """Return summary placeholder for equipment topology."""
    return {
        "containers_count": 0,
        "pcs_units_count": 0,
        "transformers_count": 0,
        "status": "UNINITIALIZED",
        "message": "Equipment models pending WP02+",
    }
