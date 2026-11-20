"""Non-negotiable safety rules and application guardrails.

This module defines hardcoded safety invariants for PowerTwin.
All external hardware integration features must remain disabled in initial phases.
"""

from typing import Final, TypedDict

# Non-negotiable safety invariant flags
SIMULATION_ONLY: Final[bool] = True
HARDWARE_INTEGRATION_ENABLED: Final[bool] = False
ALLOW_EXTERNAL_MODBUS_WRITES: Final[bool] = False
AUTOMATIC_DEVICE_DISCOVERY_ENABLED: Final[bool] = False
APPLICATION_MODE: Final[str] = "SIMULATION ONLY"


class SafetyGuardrailsReport(TypedDict):
    application_mode: str
    simulation_only: bool
    hardware_integration_enabled: bool
    allow_external_modbus_writes: bool
    automatic_device_discovery_enabled: bool
    safety_status: str


def get_safety_report() -> SafetyGuardrailsReport:
    """Return a report of active safety guardrails."""
    return {
        "application_mode": APPLICATION_MODE,
        "simulation_only": SIMULATION_ONLY,
        "hardware_integration_enabled": HARDWARE_INTEGRATION_ENABLED,
        "allow_external_modbus_writes": ALLOW_EXTERNAL_MODBUS_WRITES,
        "automatic_device_discovery_enabled": AUTOMATIC_DEVICE_DISCOVERY_ENABLED,
        "safety_status": "ACTIVE_SIMULATION_GUARDRAILS_ENFORCED",
    }
