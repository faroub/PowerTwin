"""Role-Based Access Control (RBAC) and Security Permission Management."""

import datetime
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.hash import pbkdf2_sha256
from pydantic import BaseModel, Field

from backend.app.core.config import settings

security_bearer = HTTPBearer(auto_error=False)


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


# Pre-seeded local development user accounts
DEV_USERS_DB: dict[str, dict[str, Any]] = {
    "observer": {
        "username": "observer",
        "hashed_password": pbkdf2_sha256.hash("observer123"),
        "role": UserRole.OBSERVER,
    },
    "engineer": {
        "username": "engineer",
        "hashed_password": pbkdf2_sha256.hash("engineer123"),
        "role": UserRole.ENGINEER,
    },
    "admin": {
        "username": "admin",
        "hashed_password": pbkdf2_sha256.hash("admin123"),
        "role": UserRole.ADMINISTRATOR,
    },
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password."""
    return bool(pbkdf2_sha256.verify(plain_password, hashed_password))


def create_access_token(username: str, role: UserRole) -> str:
    """Generate JWT access token for authenticated user."""
    expire = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": username,
        "role": role.value,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> UserSession:
    """Decode and validate JWT access token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub", "")
        role_str: str = payload.get("role", "")
        if not username or not role_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid session token payload.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        role = UserRole(role_str)
        return create_user_session(username, role)
    except jwt.ExpiredSignatureError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err


async def get_current_user(
    auth: HTTPAuthorizationCredentials | None = Depends(security_bearer),
) -> UserSession:
    """FastAPI Dependency enforcing authentication for protected endpoints."""
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(auth.credentials)


def require_permission(required_permission: Permission) -> Callable[..., Any]:
    """FastAPI Dependency Factory enforcing deny-by-default permission checks."""

    async def permission_dependency(
        current_user: UserSession = Depends(get_current_user),
    ) -> UserSession:
        if not current_user.has_permission(required_permission):
            msg = (
                f"Access denied. User role '{current_user.role.value}' "
                f"lacks required permission '{required_permission.value}'."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=msg,
            )
        return current_user

    return permission_dependency
