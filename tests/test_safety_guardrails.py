"""Test non-negotiable safety guardrails and startup invariant validation."""

import pytest

from backend.app.core.config import settings
from backend.app.core.safety import (
    APPLICATION_MODE,
    AUTOMATIC_DEVICE_DISCOVERY_ENABLED,
    HARDWARE_INTEGRATION_ENABLED,
    SIMULATION_ONLY,
    get_safety_report,
    validate_safety_invariants,
)


def test_safety_invariants() -> None:
    """Verify safety flags are strictly set to simulation-only safe values."""
    assert SIMULATION_ONLY is True
    assert HARDWARE_INTEGRATION_ENABLED is False
    assert settings.ALLOW_EXTERNAL_MODBUS_WRITES is False
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


def test_validate_safety_invariants_success_in_dev_mode() -> None:
    """Verify safety invariant validation passes under normal development configuration."""
    validate_safety_invariants()


def test_validate_safety_invariants_rejection_in_production_with_dev_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify safety validation raises RuntimeError in production mode when
    default secrets exist."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "JWT_SECRET_KEY",
        "default_powertwin_dev_secret_key_change_in_production",
    )

    with pytest.raises(RuntimeError) as exc_info:
        validate_safety_invariants()

    assert "SECURITY VIOLATION" in str(exc_info.value)
