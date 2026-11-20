"""Test non-negotiable safety guardrails."""

from backend.app.core.safety import (
    ALLOW_EXTERNAL_MODBUS_WRITES,
    APPLICATION_MODE,
    AUTOMATIC_DEVICE_DISCOVERY_ENABLED,
    HARDWARE_INTEGRATION_ENABLED,
    SIMULATION_ONLY,
    get_safety_report,
)


def test_safety_invariants() -> None:
    """Verify safety flags are strictly set to simulation-only safe values."""
    assert SIMULATION_ONLY is True
    assert HARDWARE_INTEGRATION_ENABLED is False
    assert ALLOW_EXTERNAL_MODBUS_WRITES is False
    assert AUTOMATIC_DEVICE_DISCOVERY_ENABLED is False
    assert APPLICATION_MODE == "SIMULATION ONLY"


def test_safety_report() -> None:
    """Verify safety report dictionary output."""
    report = get_safety_report()
    assert report["application_mode"] == "SIMULATION ONLY"
    assert report["simulation_only"] is True
    assert report["hardware_integration_enabled"] is False
    assert report["allow_external_modbus_writes"] is False
    assert report["automatic_device_discovery_enabled"] is False
    assert report["safety_status"] == "ACTIVE_SIMULATION_GUARDRAILS_ENFORCED"
