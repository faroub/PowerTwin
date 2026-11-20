"""Automated Unit Tests for WP13 Deployment Hardening and RBAC Permissions."""

import yaml

from backend.app.core.config_audit import ConfigChangeAuditLog
from backend.app.core.rbac import Permission, UserRole, create_user_session


def test_rbac_observer_role_permissions() -> None:
    """Test OBSERVER role has read-only access and cannot inject faults or modify simulation."""
    session = create_user_session("operator_read_only", UserRole.OBSERVER)

    assert session.has_permission(Permission.READ_TELEMETRY) is True
    assert session.has_permission(Permission.READ_CONFIG) is True
    assert session.has_permission(Permission.INJECT_FAULT) is False
    assert session.has_permission(Permission.MODIFY_SIMULATION) is False
    assert session.has_permission(Permission.ADMINISTER_SYSTEM) is False


def test_rbac_engineer_role_permissions() -> None:
    """Test ENGINEER role can execute scenarios and inject faults, but cannot administer plugins."""
    session = create_user_session("engineer_user", UserRole.ENGINEER)

    assert session.has_permission(Permission.READ_TELEMETRY) is True
    assert session.has_permission(Permission.EXECUTE_SCENARIO) is True
    assert session.has_permission(Permission.INJECT_FAULT) is True
    assert session.has_permission(Permission.MANAGE_PLUGINS) is False


def test_rbac_administrator_role_permissions() -> None:
    """Test ADMINISTRATOR role possesses full permissions."""
    session = create_user_session("admin_user", UserRole.ADMINISTRATOR)

    assert session.has_permission(Permission.READ_TELEMETRY) is True
    assert session.has_permission(Permission.INJECT_FAULT) is True
    assert session.has_permission(Permission.MANAGE_PLUGINS) is True
    assert session.has_permission(Permission.ADMINISTER_SYSTEM) is True


def test_config_change_audit_logging() -> None:
    """Test configuration modification event audit logging."""
    audit_log = ConfigChangeAuditLog()
    record = audit_log.log_change(
        timestamp_ns=1_000_000_000,
        user_id="admin_user",
        component_name="PPC",
        parameter_name="priority_mode",
        old_value="ACTIVE_POWER_PRIORITY",
        new_value="REACTIVE_POWER_PRIORITY",
        reason="GRID_CODE_COMPLIANCE",
    )

    assert record.user_id == "admin_user"
    assert record.component_name == "PPC"
    assert len(audit_log.entries) == 1


def test_industrial_server_profile_safety_verification() -> None:
    """Test Industrial Server deployment profile strictly disables hardware integration."""
    with open("deployment/profiles/industrial_server.yaml", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    assert profile["profile_name"] == "INDUSTRIAL_SERVER"
    assert profile["safety_guardrails"]["application_mode"] == "SIMULATION ONLY"
    assert profile["safety_guardrails"]["hardware_integration_enabled"] is False
    assert profile["safety_guardrails"]["bind_host"] in ("127.0.0.1", "localhost")
