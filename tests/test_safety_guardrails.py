"""Test non-negotiable safety guardrails and startup invariant validation."""

import pytest

from backend.app.core.config import settings
from backend.app.core.safety import (
    APPLICATION_MODE,
    AUTOMATIC_DEVICE_DISCOVERY_ENABLED,
    HARDWARE_INTEGRATION_ENABLED,
    JWT_SECRET_MIN_BYTES,
    POSTGRES_PASSWORD_MIN_BYTES,
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


def test_validate_safety_invariants_rejection_of_missing_token_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify safety validation raises RuntimeError when the production secret is empty."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "")
    monkeypatch.setattr(
        settings, "POSTGRES_PASSWORD", "a" * POSTGRES_PASSWORD_MIN_BYTES
    )

    with pytest.raises(RuntimeError) as exc_info:
        validate_safety_invariants()

    assert "SECURITY VIOLATION" in str(exc_info.value)
    assert "JWT signing secret" in str(exc_info.value)


def test_validate_safety_invariants_rejection_of_weak_token_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify safety validation raises RuntimeError when the production secret is weak."""
    weak_secret = "very" * 6
    assert len(weak_secret) < JWT_SECRET_MIN_BYTES

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", weak_secret)
    monkeypatch.setattr(
        settings, "POSTGRES_PASSWORD", "a" * POSTGRES_PASSWORD_MIN_BYTES
    )

    with pytest.raises(RuntimeError) as exc_info:
        validate_safety_invariants()

    assert "SECURITY VIOLATION" in str(exc_info.value)
    assert "JWT signing secret" in str(exc_info.value)


def test_validate_safety_invariants_rejection_of_weak_database_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify safety validation raises RuntimeError when the production password is weak."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "a" * JWT_SECRET_MIN_BYTES)
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", "short_password")

    with pytest.raises(RuntimeError) as exc_info:
        validate_safety_invariants()

    assert "SECURITY VIOLATION" in str(exc_info.value)
    assert "database password" in str(exc_info.value)


def test_validate_safety_invariants_rejection_of_invalid_login_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify safety validation raises RuntimeError when login limits are unusable."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "a" * JWT_SECRET_MIN_BYTES)
    monkeypatch.setattr(
        settings, "POSTGRES_PASSWORD", "a" * POSTGRES_PASSWORD_MIN_BYTES
    )
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT", -1)

    with pytest.raises(RuntimeError) as exc_info:
        validate_safety_invariants()

    assert "SECURITY VIOLATION" in str(exc_info.value)


def test_validate_safety_invariants_production_with_strong_config_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify safety validation passes with a strong production configuration."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "a" * JWT_SECRET_MIN_BYTES)
    monkeypatch.setattr(
        settings, "POSTGRES_PASSWORD", "b" * POSTGRES_PASSWORD_MIN_BYTES
    )

    validate_safety_invariants()


def test_validate_safety_invariants_rejects_nonloopback_modbus_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Modbus writes refuse a non-loopback host binding in production mode."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "a" * JWT_SECRET_MIN_BYTES)
    monkeypatch.setattr(
        settings, "POSTGRES_PASSWORD", "b" * POSTGRES_PASSWORD_MIN_BYTES
    )
    monkeypatch.setattr(settings, "ALLOW_EXTERNAL_MODBUS_WRITES", True)
    monkeypatch.setattr(settings, "PROTOCOL_GATEWAY_HOST", "192.168.1.1")

    with pytest.raises(RuntimeError) as exc_info:
        validate_safety_invariants()

    assert "INVARIANT VIOLATION" in str(exc_info.value)
    assert "non-loopback host interface" in str(exc_info.value)


@pytest.mark.asyncio
async def test_production_server_host_must_be_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify production refuses a server binding on every available interface."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "a" * JWT_SECRET_MIN_BYTES)
    monkeypatch.setattr(
        settings, "POSTGRES_PASSWORD", "b" * POSTGRES_PASSWORD_MIN_BYTES
    )
    monkeypatch.setattr(settings, "HOST", "0.0.0.0")

    with pytest.raises(RuntimeError) as exc_info:
        validate_safety_invariants()

    assert "SECURITY VIOLATION" in str(exc_info.value)
    assert "loopback" in str(exc_info.value)


@pytest.mark.asyncio
async def test_dev_mode_allows_all_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify non-production environments are unaffected by the host binding rule."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "HOST", "0.0.0.0")
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT", 5)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_SECONDS", 60)

    validate_safety_invariants()
