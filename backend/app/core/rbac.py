"""Role-Based Access Control (RBAC) and Security Permission Management."""

import datetime
import logging
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.hash import pbkdf2_sha256
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.core.revocation import (
    RevocationStoreUnavailableError,
    is_token_revoked,
)

logger = logging.getLogger(__name__)

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
    """Authenticated user session token model.

    Attributes:
        username: The account the token was issued to.
        role: The role the token carries.
        permissions: The permissions the role grants.
        token_id: The ``jti`` claim of the token — the identity the platform
            can name when it has to refuse the token. A token issued before
            the platform issued token identities carries none, and such a
            token cannot be revoked.
        expires_at: The expiry the token carries.
    """

    username: str
    role: UserRole
    permissions: set[Permission] = Field(default_factory=set)
    token_id: str = ""
    expires_at: datetime.datetime | None = None

    def has_permission(self, permission: Permission) -> bool:
        """Check if current user session possesses required permission."""
        return permission in self.permissions


def create_user_session(
    username: str,
    role: UserRole,
    *,
    token_id: str = "",
    expires_at: datetime.datetime | None = None,
) -> UserSession:
    """Create a UserSession instance populated with role permissions."""
    permissions = ROLE_PERMISSIONS.get(role, set())
    return UserSession(
        username=username,
        role=role,
        permissions=permissions,
        token_id=token_id,
        expires_at=expires_at,
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password."""
    return bool(pbkdf2_sha256.verify(plain_password, hashed_password))


def create_access_token(username: str, role: UserRole, token_id: str | None = None) -> str:
    """Generate JWT access token for authenticated user.

    Every token carries a unique ``jti`` claim. The claim is the identity the
    platform can name when it has to refuse the token — the value recorded in
    the ``revoked_tokens`` table when the session ends — so a token that was
    issued before this claim existed, and therefore carries none, can only be
    refused by its expiry.
    """
    expire = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": username,
        "role": role.value,
        "exp": expire,
        "jti": token_id or str(uuid.uuid4()),
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
        expires_at: datetime.datetime | None = None
        expiry = payload.get("exp")
        if isinstance(expiry, int | float):
            expires_at = datetime.datetime.fromtimestamp(expiry, tz=datetime.UTC)
        token_id = payload.get("jti", "")
        return create_user_session(
            username,
            role,
            token_id=str(token_id),
            expires_at=expires_at,
        )
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


async def reject_revoked_token(session: UserSession) -> None:
    """Refuse a token the platform has revoked.

    A token that carries no identity cannot be revoked and is accepted until
    it expires; that is stated in the log, because it is the one case in which
    the platform cannot refuse a token it has been handed.

    Raises:
        HTTPException: 401 when the token was revoked, and 503 when the
            production revocation store could not be read. The platform fails
            closed there: a token it could not check is a token it does not
            accept.
    """
    if not session.token_id:
        logger.warning(
            "The session token of '%s' carries no token identity; it cannot be "
            "revoked and is accepted until it expires.",
            session.username,
        )
        return

    try:
        revoked = await is_token_revoked(session.token_id)
    except RevocationStoreUnavailableError as err:
        if settings.ENVIRONMENT == "production":
            logger.error(
                "The revocation store could not be read; the token of '%s' is refused.",
                session.username,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Session validation is temporarily unavailable. Please try again.",
            ) from err
        logger.warning(
            "The revocation store could not be read; the token of '%s' is refused.",
            session.username,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err

    if revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )


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
    session = decode_access_token(auth.credentials)
    await reject_revoked_token(session)
    return session


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
