"""Authentication API Endpoints for Token Generation and User Verification."""

import datetime
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend.app.core.audit import audit_log
from backend.app.core.auth_development import validate_dev_environment
from backend.app.core.authentication import AuthenticationService
from backend.app.core.config import settings
from backend.app.core.identity import resolve_client_id
from backend.app.core.rbac import (
    Permission,
    UserSession,
    get_current_user,
    require_permission,
)
from backend.app.core.revocation import (
    REVOCATION_REASON_LOGOUT,
    RevocationStoreUnavailableError,
    purge_expired_revocations,
    revoke_token,
)
from backend.app.historian.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

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
async def login(payload: LoginRequest, request: Request) -> TokenResponse:
    """Authenticate user credentials and issue JWT session token.

    The environment decides which store supplies the identity. Development
    accounts are only accepted while the platform runs in development or
    testing mode; in every other mode `validate_dev_environment` advertises
    that provisioning is ignored before the service resolves the candidate.

    The rate limiter measures one identity per login attempt: the client
    identity of the request combined with the username it attempts. A
    client identity is the request peer address unless the peer is a trusted
    proxy, in which case the application trusts the address the proxy claims.
    """
    username = payload.username.lower()
    client_id = resolve_client_id(request)

    # The identity source is chosen by the environment, never by the caller.
    # Allowing a production process down through the development store is a
    # security violation, so the environment is checked at login-marshal time.
    validate_dev_environment()

    if settings.ENVIRONMENT == "production":
        async with AsyncSessionLocal() as session:
            result = await _auth_service.login(
                username, payload.password, session=session, client_id=client_id
            )
    else:
        result = await _auth_service.login(
            username, payload.password, session=None, client_id=client_id
        )

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
    current_user: UserSession = Depends(get_current_user),
) -> LogoutResponse:
    """Terminate the caller's own platform session (logout).

    Logout revokes the caller's access token server-side. Every token the
    platform issues carries a unique identity (``jti``), and the revocation is
    recorded in the platform's revocation store: the ``revoked_tokens`` table
    in production, the in-process store in development. A token that was
    issued before the logout is refused from that moment on — including a copy
    of it that was made before the logout. The other tokens of the same
    account keep working until they expire or are revoked in turn.

    Logout is a self-service action, so any authenticated user — including an
    observer — can end it.

    A revocation that could not be recorded is reported as a failure: the
    session was not terminated, and the endpoint says so instead of answering
    as if it had been.
    """
    audit_log.record("LOGOUT", current_user.username, "SESSION")

    if not current_user.token_id:
        # A token issued before the platform issued token identities cannot be
        # revoked. It is refused by its expiry, which is the limit the platform
        # can enforce for it.
        logger.warning(
            "The session token of '%s' carries no token identity; it cannot be revoked.",
            current_user.username,
        )
        return LogoutResponse(message="Session terminated; the access token cannot be revoked.")

    expires_at = current_user.expires_at or (
        datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    try:
        await revoke_token(
            current_user.token_id,
            current_user.username,
            expires_at,
            REVOCATION_REASON_LOGOUT,
        )
    except RevocationStoreUnavailableError as err:
        logger.error("The session of '%s' could not be revoked: %s", current_user.username, err)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The session could not be terminated. Please try again.",
        ) from err

    # The revocations of tokens that have expired by themselves are forgotten.
    # A purge that fails is a maintenance failure, not a session failure.
    await purge_expired_revocations()

    return LogoutResponse(message="Session terminated and the access token revoked.")


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
