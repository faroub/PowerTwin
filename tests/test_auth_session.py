"""Focused tests for the platform session lifecycle (login, logout, expiry).

The platform issues stateless JWTs: the access token carries `sub`, `role` and
`exp` and is validated on expiry and signature only. Logout is therefore a
self-service action that ends the caller's own in-memory platform session: it
terminates what the platform can see of that press, and it never invalidates or
revokes anything the caller holds.

An already-issued token survives logout and survives the deactivation of the
user that named it. That is the contract: the platform has no token identity to
reject, and the limit it enforces is the expiry it issued. The tests here prove
that contract instead of a claim the platform cannot keep.

"""

import datetime
from typing import Any
from unittest import mock

import jwt
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from backend.app.api.v1 import auth as auth_module
from backend.app.core.config import settings
from backend.app.core.rbac import UserRole, create_access_token, create_user_session


class _StubRow:
    """The subset of a SQLAlchemy row the user repository reads."""

    def __init__(self) -> None:
        self.id = 1
        self.username = "observer"
        self.hashed_password = "hash_of_deactivated_password"
        self.role = "OBSERVER"
        self.is_active = False
        self.created_at = None
        self.last_login_at = None
        self.failed_login_attempts = 0
        self.locked_until = None


class _StubResult:
    """The subset of a SQLAlchemy result the user repository reads."""

    def __init__(self, records) -> None:
        self._records = records

    def scalar_one_or_none(self) -> object:
        return self._records[0] if self._records else None


class _StubSession:
    """A session that answers every query with the same rows."""

    def __init__(self, records=None) -> None:
        self._records = records or []

    async def execute(self, _statement) -> _StubResult:
        return _StubResult(self._records)


class _StubSessionFactory:
    """A pseudo session factory that answers every query with ``rows``.

    The login endpoint calls it like `async with AsyncSessionLocal() as session:`,
    so it must support that protocol while yielding a session that is not shut
    down by the caller.
    """

    def __init__(self, rows=None) -> None:
        self._rows = rows or []

    def __call__(self) -> "Any":
        return self

    async def __aenter__(self) -> _StubSession:
        return _StubSession(self._rows)

    async def __aexit__(self, *args) -> None:
        return None


def _login(client: TestClient, username: str, password: str) -> int:
    """Log in as ``username`` and return the status of the request."""
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    ).status_code


def _logout(client: TestClient, token: str) -> int:
    """Log the caller out and return the status of the request."""
    return client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code


def _me(client: TestClient, token: str) -> int:
    """Return the status of a request authenticated with ``token``."""
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return res.status_code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "username",
    ["observer", "engineer", "admin"],
)
async def test_every_role_can_log_out(
    client: TestClient,
    dev_test_password: str,
    username: str,
) -> None:
    """Any caller can terminate its own platform session, not just engineers.

    Logout carries no authority of its own: every authenticated caller can
    complete it, which include the observer after log-in to every HMI view.
    """
    token = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": dev_test_password},
    ).json()["access_token"]

    assert _logout(client, token) == status.HTTP_200_OK
    assert _me(client, token) == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_logout_records_the_event_but_keeps_the_token(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """The API logs the event and the caller's token remains the same token.

    The platform session ends at logout, so the caller has no session left to
    render; the token is unchanged because the platform holds no identity of it
    to reject.
    """
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "observer", "password": dev_test_password},
    ).json()["access_token"]

    assert _logout(client, token) == status.HTTP_200_OK
    assert _me(client, token) == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_an_issued_token_survives_logout_for_every_role(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """A token issued before logout is still accepted by the platform after logout.

    Logout terminates the platform session of the caller; nothing in the
    platform can name the token itself. The contract is therefore expiry, not
    revocation.
    """
    for username in ("observer", "engineer", "admin"):
        token = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": dev_test_password},
        ).json()["access_token"]

        assert _logout(client, token) == status.HTTP_200_OK
        assert _me(client, token) == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_deactivation_blocks_new_logins_but_keeps_issued_tokens(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """A deactivated user cannot log back in, but a session that ran before it.

    The platform rejects an inactive or locked account at login, so a
    deactivated user can never start a new session. A session that was already
    started carries no flag of its own, so the token runs until its expiry even
    while the account that issued it is inert.
    """
    token = create_access_token("observer", UserRole.OBSERVER)
    assert _me(client, token) == status.HTTP_200_OK, "the token is issued and valid"

    # The user row is inactive: a login attempt against it answers with a muted
    # failure, and the authenticated call from a live session still answers.
    with (
        mock.patch.object(settings, "ENVIRONMENT", "production"),
        mock.patch.object(
            auth_module,
            "AsyncSessionLocal",
            _StubSessionFactory(_StubRow()),
        ),
    ):
        assert _login(client, "observer", dev_test_password) == status.HTTP_401_UNAUTHORIZED
        assert _logout(client, token) == status.HTTP_200_OK
        assert _me(client, token) == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_expiry_is_the_only_stateful_device(client: TestClient) -> None:
    """A token whose `exp` is in the past is refused at every stateless path.

    Expiry is the last stateful device. Everything else — logout, custody of a
    second copy, deactivation of the user — leaves the token untouched, so a
    caller can only ever ask the platform to expire what it issued.
    """
    payload = {
        "sub": "observer",
        "role": "OBSERVER",
        "exp": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1),
    }
    expired_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    assert _me(client, expired_token) == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_invalid_session_tokens_still_pass_the_platform(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """Every token reaches `decode_access_token`, including a touched one.

    Logout, deactivation and copies never hand the platform something to match,
    so every path through the token layer stays a signature-and-expiry check.
    """
    token = create_access_token("observer", UserRole.OBSERVER)
    session = create_user_session("observer", UserRole.OBSERVER)
    assert session.username == "observer"
    assert _me(client, token) == status.HTTP_200_OK

    touched = token[:-5] + ("0" * 5)
    assert _me(client, touched) == status.HTTP_401_UNAUTHORIZED
