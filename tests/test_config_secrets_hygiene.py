"""Tests for Configuration and Secrets Hygiene.

These tests verify that:
    * Secrets are redacted before they reach an audit trail.
    * Configuration templates never ship a credential or a non-loopback bind.
    * A blank environment variable is never mistaken for a configured secret.
"""

import pathlib

import pytest

from backend.app.core.audit import AuditLog
from backend.app.core.config import Settings
from backend.app.core.config_audit import ConfigChangeAuditLog
from backend.app.core.secrets import (
    REDACTED_PLACEHOLDER,
    is_sensitive_name,
    redact_details,
    redact_mapping,
    redact_text,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_TEMPLATES = (
    REPO_ROOT / ".env.example",
    REPO_ROOT / "configs" / ".env.example",
)


# =============================================================================
# Secret redaction helpers
# =============================================================================


@pytest.mark.parametrize(
    "name",
    [
        "password",
        "PASSWORD",
        "POSTGRES_PASSWORD",
        "db_password",
        "db-password",
        "jwt_secret",
        "JWT_SECRET_KEY",
        "api_key",
        "apikey",
        "access_token",
        "private_key",
        "passphrase",
        "credential",
        "authorization",
        "signature",
    ],
)
def test_sensitive_names_are_detected(name: str) -> None:
    """Test that credential-like parameter names are detected."""
    assert is_sensitive_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "username",
        "host",
        "port",
        "tick_rate_hz",
        "simulation_speed_factor",
        "log_level",
    ],
)
def test_non_sensitive_names_are_not_redacted(name: str) -> None:
    """Test that ordinary configuration names are not treated as secrets."""
    assert is_sensitive_name(name) is False


def test_redact_mapping_replaces_sensitive_values() -> None:
    """Test a mapping with a credential has the credential replaced."""
    redacted = redact_mapping(
        {
            "username": "powertwin",
            "password": "super-secret-value",
            "nested": {"api_key": "another-secret", "host": "db"},
            "items": [{"token": "tok"}],
        }
    )

    assert redacted["username"] == "powertwin"
    assert redacted["password"] == REDACTED_PLACEHOLDER
    assert redacted["nested"]["api_key"] == REDACTED_PLACEHOLDER
    assert redacted["nested"]["host"] == "db"
    assert redacted["items"][0]["token"] == REDACTED_PLACEHOLDER


def test_redact_text_removes_embedded_url_credentials() -> None:
    """Test a connection URL with an embedded password is redacted."""
    redacted = redact_text("postgresql+asyncpg://user:hunter2@db:5432/powertwin")
    assert "hunter2" not in redacted
    assert REDACTED_PLACEHOLDER in redacted


def test_redact_details_walks_nested_structures() -> None:
    """Test nested mappings and sequences are redacted recursively."""
    redacted = redact_details(
        {"outer": {"password": "p"}, "list": [{"secret": "s"}], "plain": "value"}
    )
    assert redacted["outer"]["password"] == REDACTED_PLACEHOLDER
    assert redacted["list"][0]["secret"] == REDACTED_PLACEHOLDER
    assert redacted["plain"] == "value"


# =============================================================================
# Audit trails never store credentials
# =============================================================================


def test_config_change_audit_redacts_sensitive_parameter() -> None:
    """Test a configuration change of a password is redacted in the audit log."""
    log = ConfigChangeAuditLog()
    record = log.log_change(
        timestamp_ns=1_000,
        user_id="admin",
        component_name="database",
        parameter_name="POSTGRES_PASSWORD",
        old_value="old-secret",
        new_value="new-secret",
    )

    assert record.old_value == REDACTED_PLACEHOLDER
    assert record.new_value == REDACTED_PLACEHOLDER
    assert "old-secret" not in record.old_value
    assert "new-secret" not in record.new_value


def test_config_change_audit_keeps_non_sensitive_values() -> None:
    """Test an ordinary configuration change is still recorded verbatim."""
    log = ConfigChangeAuditLog()
    record = log.log_change(
        timestamp_ns=1_000,
        user_id="admin",
        component_name="simulation",
        parameter_name="tick_rate_hz",
        old_value="50",
        new_value="100",
    )

    assert record.old_value == "50"
    assert record.new_value == "100"


def test_audit_log_redacts_sensitive_details(tmp_path: pathlib.Path) -> None:
    """Test the operational audit log redacts credentials in its details."""
    log = AuditLog(log_dir=str(tmp_path))
    event = log.record(
        action="CONFIGURATION_UPDATED",
        actor="admin",
        target="database",
        details={"password": "leaked-secret", "host": "db"},
    )

    assert event.details["password"] == REDACTED_PLACEHOLDER
    assert event.details["host"] == "db"
    assert "leaked-secret" not in event.model_dump_json()


def test_audit_log_failure_record_redacts_sensitive_details(
    tmp_path: pathlib.Path,
) -> None:
    """Test a failed audit event is redacted as well."""
    log = AuditLog(log_dir=str(tmp_path))
    event = log.record_failure(
        action="LOGIN_FAILED",
        actor="observer",
        target="auth",
        details={"password": "leaked-secret"},
    )

    assert event.outcome == "FAILURE"
    assert event.details["password"] == REDACTED_PLACEHOLDER


# =============================================================================
# Configuration templates
# =============================================================================


@pytest.mark.parametrize("template", ENV_TEMPLATES, ids=lambda p: p.name)
def test_env_templates_bind_to_loopback(template: pathlib.Path) -> None:
    """Test no environment template binds the API server to a public interface."""
    content = template.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("HOST="):
            host = stripped.split("=", 1)[1].strip()
            assert host == "127.0.0.1", (
                f"{template.name} binds the API server to '{host}'; the writable "
                "control interface must stay on the loopback interface."
            )


@pytest.mark.parametrize("template", ENV_TEMPLATES, ids=lambda p: p.name)
def test_env_templates_ship_no_credential(template: pathlib.Path) -> None:
    """Test no environment template contains a usable credential value.

    A placeholder such as ``<your-secure-password>`` is rejected as well: it
    is a publicly known value that becomes a real credential the moment the
    template is copied verbatim.
    """
    content = template.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip().upper()
        if not any(
            fragment in name
            for fragment in ("PASSWORD", "SECRET", "TOKEN", "KEY", "CREDENTIAL")
        ):
            continue
        assert value.strip() == "", (
            f"{template.name} ships a value for '{name}'. Template files must "
            "leave every credential empty so that an unset secret fails fast "
            "instead of starting with a publicly known credential."
        )


@pytest.mark.parametrize("template", ENV_TEMPLATES, ids=lambda p: p.name)
def test_env_templates_disable_external_modbus_writes(template: pathlib.Path) -> None:
    """Test the external controller write path is disabled in every template."""
    content = template.read_text(encoding="utf-8")
    assert "ALLOW_EXTERNAL_MODBUS_WRITES=False" in content


@pytest.mark.parametrize("template", ENV_TEMPLATES, ids=lambda p: p.name)
def test_env_templates_document_the_protocol_gateway_binding(
    template: pathlib.Path,
) -> None:
    """Test every template pins the protocol gateway to the loopback interface."""
    content = template.read_text(encoding="utf-8")
    assert "PROTOCOL_GATEWAY_HOST=127.0.0.1" in content


# =============================================================================
# Blank environment variables are never treated as configured secrets
# =============================================================================


def test_blank_postgres_password_falls_back_to_random(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test an exported-but-empty POSTGRES_PASSWORD is not used as the credential."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "")
    settings = Settings()
    assert settings.POSTGRES_PASSWORD != ""
    assert len(settings.POSTGRES_PASSWORD) >= 32


def test_whitespace_postgres_password_falls_back_to_random(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a whitespace-only POSTGRES_PASSWORD is not used as the credential."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "   ")
    settings = Settings()
    assert settings.POSTGRES_PASSWORD.strip() != ""


def test_configured_postgres_password_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test an explicitly configured POSTGRES_PASSWORD is honoured."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "a-strong-test-password-value")
    settings = Settings()
    assert settings.POSTGRES_PASSWORD == "a-strong-test-password-value"


def test_redacted_database_url_never_contains_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the redacted connection URL never carries the real credential."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "a-strong-test-password-value")
    settings = Settings()
    assert "a-strong-test-password-value" not in settings.REDACTED_DATABASE_URL
    assert REDACTED_PLACEHOLDER in settings.REDACTED_DATABASE_URL
