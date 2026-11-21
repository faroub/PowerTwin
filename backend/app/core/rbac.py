"""Role-Based Access Control (RBAC) and Security Permission Management."""

from enum import StrEnum

from pydantic import BaseModel, Field


class UserRole(StrEnum):
    """User Operational Roles."""

    OBSERVER = "OBSERVER"  # Read-only HMI & Telemetry access
    ENGINEER = "ENGINEER"  # Simulation parameters, scenario execution, fault injection
    ADMINISTRATOR = "ADMINISTRATOR"  # Full system configuration, plugin management, user management


class Permission(StrEnum):
    """System Permission Identifiers."""

    READ_TELEMETRY = "READ_TELEMETRY"
    READ_CONFIG = "READ_CONFIG"
    EXECUTE_SCENARIO = "EXECUTE_SCENARIO"
    INJECT_FAULT = "INJECT_FAULT"
    MODIFY_SIMULATION = "MODIFY_SIMULATION"
    MANAGE_PLUGINS = "MANAGE_PLUGINS"
    ADMINISTER_SYSTEM = "ADMINISTER_SYSTEM"


ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.OBSERVER: {
        Permission.READ_TELEMETRY,
        Permission.READ_CONFIG,
    },
    UserRole.ENGINEER: {
        Permission.READ_TELEMETRY,
        Permission.READ_CONFIG,
        Permission.EXECUTE_SCENARIO,
        Permission.INJECT_FAULT,
        Permission.MODIFY_SIMULATION,
    },
    UserRole.ADMINISTRATOR: {
        Permission.READ_TELEMETRY,
        Permission.READ_CONFIG,
        Permission.EXECUTE_SCENARIO,
        Permission.INJECT_FAULT,
        Permission.MODIFY_SIMULATION,
        Permission.MANAGE_PLUGINS,
        Permission.ADMINISTER_SYSTEM,
    },
}


class UserSession(BaseModel):
    """Authenticated user session token model."""

    username: str
    role: UserRole
    permissions: set[Permission] = Field(default_factory=set)

    def has_permission(self, permission: Permission) -> bool:
        """Check if current user session possesses required permission."""
        return permission in self.permissions


def create_user_session(username: str, role: UserRole) -> UserSession:
    """Create a UserSession instance populated with role permissions."""
    permissions = ROLE_PERMISSIONS.get(role, set())
    return UserSession(username=username, role=role, permissions=permissions)
