"""Non-negotiable safety rules and application guardrails.

This module defines hardcoded safety invariants for PowerTwin.
All physical hardware integration features remain strictly disabled.
"""

import logging
from typing import Final, TypedDict

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Non-negotiable safety invariant flags
SIMULATION_ONLY: Final[bool] = True
HARDWARE_INTEGRATION_ENABLED: Final[bool] = False
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
    """Return an authoritative report of active safety guardrails."""
    return {
        "application_mode": APPLICATION_MODE,
        "simulation_only": SIMULATION_ONLY,
        "hardware_integration_enabled": HARDWARE_INTEGRATION_ENABLED,
        "allow_external_modbus_writes": settings.ALLOW_EXTERNAL_MODBUS_WRITES,
        "automatic_device_discovery_enabled": AUTOMATIC_DEVICE_DISCOVERY_ENABLED,
        "safety_status": "ACTIVE_SIMULATION_GUARDRAILS_ENFORCED",
    }


def validate_safety_invariants() -> None:
    """Validate all safety and configuration invariants on startup.

    Raises:
        RuntimeError: If any safety invariant or security boundary is violated.
    """
    # 1. Non-negotiable physical hardware isolation checks
    if not SIMULATION_ONLY or HARDWARE_INTEGRATION_ENABLED or AUTOMATIC_DEVICE_DISCOVERY_ENABLED:
        msg = (
            "SAFETY INVARIANT VIOLATION: Physical hardware integration or discovery is prohibited."
        )
        logger.critical(msg)
        raise RuntimeError(msg)

    # 2. Protocol Gateway CIL Host Interface Binding Check
    if settings.ALLOW_EXTERNAL_MODBUS_WRITES:
        if settings.PROTOCOL_GATEWAY_HOST not in ("127.0.0.1", "localhost", "::1"):
            msg = (
                f"SAFETY INVARIANT VIOLATION: Refusing to enable Modbus writes on "
                f"non-loopback host interface '{settings.PROTOCOL_GATEWAY_HOST}'."
            )
            logger.critical(msg)
            raise RuntimeError(msg)

    # 3. Production Security & Secret Invariant Validation
    if settings.ENVIRONMENT == "production":
        dev_secret = "default_powertwin_dev_secret_key_change_in_production"
        if settings.JWT_SECRET_KEY == dev_secret:
            msg = (
                "SECURITY VIOLATION: Default development JWT_SECRET_KEY "
                "cannot be used in production."
            )
            logger.critical(msg)
            raise RuntimeError(msg)

        if settings.POSTGRES_PASSWORD == "powertwin_secret":
            msg = (
                "SECURITY VIOLATION: Default POSTGRES_PASSWORD "
                "cannot be used in production environment."
            )
            logger.critical(msg)
            raise RuntimeError(msg)

    logger.info("All application safety and security invariants validated successfully.")
