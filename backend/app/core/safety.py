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

# Minimum length of the JWT signing secret in bytes. Secrets shorter than this
# cannot withstand offline dictionary attacks and must be rejected in production.
JWT_SECRET_MIN_BYTES: Final[int] = 32

# Minimum length of the database password in characters.
POSTGRES_PASSWORD_MIN_BYTES: Final[int] = 20


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


def _validate_token_secret() -> None:
    """Reject an empty or weak JWT signing secret in production deployments.

    Development and testing environments generate a per-process random secret,
    while production deployments that rely on the default value can never sign
    tokens securely. Failing closed here prevents accidental acceptance of an
    unprotected process.
    """
    if settings.ENVIRONMENT not in ("production",):
        return

    if not settings.JWT_SECRET_KEY or len(settings.JWT_SECRET_KEY) < JWT_SECRET_MIN_BYTES:
        msg = (
            "SECURITY VIOLATION: The JWT signing secret must be at least "
            f"{JWT_SECRET_MIN_BYTES} characters; an empty secret can never "
            "protect session tokens in a production deployment."
        )
        logger.critical(msg)
        raise RuntimeError(msg)


def _validate_database_password() -> None:
    """Reject a default or weak database password in production deployments."""
    if settings.ENVIRONMENT not in ("production",):
        return

    if not settings.POSTGRES_PASSWORD:
        msg = (
            "SECURITY VIOLATION: The database password must be at least "
            f"{POSTGRES_PASSWORD_MIN_BYTES} characters; a default or weak "
            "password enables offline brute-force attacks against the historian."
        )
        logger.critical(msg)
        raise RuntimeError(msg)

    if len(settings.POSTGRES_PASSWORD) < POSTGRES_PASSWORD_MIN_BYTES:
        msg = (
            "SECURITY VIOLATION: The database password must be at least "
            f"{POSTGRES_PASSWORD_MIN_BYTES} characters; a default or weak "
            "password enables offline brute-force attacks against the historian."
        )
        logger.critical(msg)
        raise RuntimeError(msg)


def _validate_server_binding() -> None:
    """Reject a non-loopback server binding in production deployments.

    A writable interface exposed to untrusted networks is a safety violation;
    production deployments must keep the API bound to the loopback interface
    unless an explicit, documented external binding is required.
    """
    if settings.ENVIRONMENT not in ("production",):
        return

    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    if settings.HOST not in loopback_hosts:
        msg = (
            f"SECURITY VIOLATION: The production server host '{settings.HOST}' "
            "must be bound to a loopback interface; a non-loopback host exposes "
            "writable control interfaces to untrusted networks."
        )
        logger.critical(msg)
        raise RuntimeError(msg)


def _validate_login_limits() -> None:
    """Reject unreasonable authentication rate-limit settings."""
    if settings.LOGIN_RATE_LIMIT > 0 and settings.LOGIN_LOCKOUT_SECONDS > 0:
        return
    msg = (
        "SECURITY VIOLATION: LOGIN_RATE_LIMIT and LOGIN_LOCKOUT_SECONDS must "
        "both be positive; an invalid rate limit disables login throttling."
    )
    logger.critical(msg)
    raise RuntimeError(msg)


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

    # 3. Production server binding must remain loopback unless explicitly
    #    documented and configured otherwise.
    _validate_server_binding()

    # 4. Authentication and Secret Invariant Validation
    _validate_token_secret()
    _validate_database_password()
    _validate_login_limits()

    logger.info("All application safety and security invariants validated successfully.")
