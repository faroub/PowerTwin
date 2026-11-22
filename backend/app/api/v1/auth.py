"""Authentication API Endpoints for Token Generation and User Verification."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.app.core.config import settings
from backend.app.core.rbac import (
    DEV_USERS_DB,
    UserRole,
    UserSession,
    create_access_token,
    get_current_user,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    """User login request payload."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """JWT Token response payload."""

    access_token: str
    token_type: str = "bearer"
    username: str
    role: UserRole


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    """Authenticate user credentials and issue JWT session token."""
    username = payload.username.lower()

    if settings.ENVIRONMENT == "development":
        user_data = DEV_USERS_DB.get(username)
        if not user_data or not verify_password(payload.password, user_data["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        role = user_data["role"]
    else:
        # In non-development environment, require secure production user verification
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Production user authentication requires database identity provider.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(username, role)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        username=username,
        role=role,
    )


@router.get("/me", response_model=dict[str, Any])
async def get_me(current_user: UserSession = Depends(get_current_user)) -> dict[str, Any]:
    """Return authenticated user session profile."""
    return {
        "username": current_user.username,
        "role": current_user.role,
        "permissions": [p.value for p in current_user.permissions],
    }
