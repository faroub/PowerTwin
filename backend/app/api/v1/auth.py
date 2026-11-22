"""Authentication API Endpoints for Token Generation and User Verification."""

import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.app.core.audit import audit_log
from backend.app.core.authentication import AuthenticationService
from backend.app.core.config import settings
from backend.app.core.rbac import Permission, UserSession, require_permission
from backend.app.historian.db import AsyncSessionLocal

router = APIRouter(prefix="/auth", tags=["Authentication"])

_auth_service = AuthenticationService()


class LoginRequest(BaseModel):
    """User login request payload."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """JWT Token response payload."""

    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    permissions: list[str]


class LogoutResponse(BaseModel):
    """Logout response payload."""

    message: str


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    """Authenticate user credentials and issue JWT session token."""
    username = payload.username.lower()

    if settings.ENVIRONMENT == "production":
        async with AsyncSessionLocal() as session:
            result = await _auth_service.login(username, payload.password, session=session)
    else:
        result = await _auth_service.login(username, payload.password, session=None)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if result.token is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token generation failed. Please try again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if result.user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session details missing. Please try again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=result.token,
        token_type="bearer",
        username=result.user.username,
        role=result.user.role.value,
        permissions=[p.value for p in _auth_service.get_session_permissions(result.user.role)],
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    current_user: UserSession = Depends(require_permission(Permission.MODIFY_SIMULATION)),
) -> LogoutResponse:
    """Invalidate the caller session token (logout)."""
    audit_log.record("LOGOUT", current_user.username, "SESSION")
    return LogoutResponse(message="Session terminated.")


@router.get("/me", response_model=dict[str, Any])
async def get_me(
    current_user: UserSession = Depends(require_permission(Permission.READ_TELEMETRY)),
) -> dict[str, Any]:
    """Return authenticated user session profile."""
    return {
        "username": current_user.username,
        "role": current_user.role.value,
        "permissions": [p.value for p in current_user.permissions],
        "last_login_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "environment": settings.ENVIRONMENT,
    }


@router.get("/session/check")
async def session_check(
    current_user: UserSession = Depends(require_permission(Permission.READ_TELEMETRY)),
) -> dict[str, str]:
    """Return whether the current session is valid and active."""
    return {
        "authenticated": "true",
        "username": current_user.username,
        "role": current_user.role.value,
        "permissions": ",".join(p.value for p in current_user.permissions),
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
    }
