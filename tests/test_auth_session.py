"""Focused tests for the platform session lifecycle (login, logout, expiry).

The platform issues stateless JWTs that carry a unique identity (``jti``).
Logout records that identity in the revocation store of the environment, and
every protected route refuses a token the store names. The tests here pin that
contract down:

* the token of the caller is refused from the moment it is logged out;
* the other tokens of the same account keep working;
* a token that predates the token identity cannot be revoked and is accepted
  until it expires — the platform says so rather than pretending otherwise.

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

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


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


def _token(client: TestClient, username: str, password: str) -> str:
    """Log in as ``username`` and return the access token."""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return str(response.json()["access_token"])


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


def _token_without_identity() -> str:
    """Return a token that carries no ``jti`` claim."""
    payload = {
        "sub": "observer",
        "role": "OBSERVER",
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=60),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


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
    complete it, which includes the observer after log-in to every HMI view.
    """
    token = _token(client, username, dev_test_password)

    assert _logout(client, token) == status.HTTP_200_OK
    assert _me(client, token) == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_the_token_of_the_caller_is_refused_after_the_logout(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """A logout ends the session of the caller on the server, not only in the browser.

    The platform records the identity of the token it issued, so the token is
    refused at every protected route from that moment on — including a copy
    of it that was made before the logout.
    """
    token = _token(client, "observer", dev_test_password)
    assert _me(client, token) == status.HTTP_200_OK

    assert _logout(client, token) == status.HTTP_200_OK

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "revoked" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_the_other_tokens_of_the_account_keep_working(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """A logout revokes the token that was used, and only that token.

    The other sessions of the same account are unaffected: they keep working
    until they expire or are ended in turn.
    """
    first = _token(client, "observer", dev_test_password)
    second = _token(client, "observer", dev_test_password)

    assert _logout(client, first) == status.HTTP_200_OK

    assert _me(client, first) == status.HTTP_401_UNAUTHORIZED
    assert _me(client, second) == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_a_revoked_token_cannot_end_another_session(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """A token that was revoked can no longer be used to act on the platform."""
    revoked = _token(client, "observer", dev_test_password)
    live = _token(client, "observer", dev_test_password)

    assert _logout(client, revoked) == status.HTTP_200_OK

    # The revoked token is refused at the door, so the second logout never
    # reaches the revocation store and the live token is untouched.
    assert _logout(client, revoked) == status.HTTP_401_UNAUTHORIZED
    assert _me(client, live) == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_a_deactivated_account_cannot_log_in_again(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """A deactivated user cannot start a new session.

    The platform rejects an inactive or locked account at login, so a
    deactivated user can never start a new session. A session that was already
    started runs until it is ended: the platform does not retroactively revoke
    the tokens of an account, it only refuses a token it has been told to
    refuse.
    """
    token = _token(client, "observer", dev_test_password)
    assert _me(client, token) == status.HTTP_200_OK, "the token is issued and valid"

    # The user row is inactive: a login attempt against it answers with a muted
    # failure, while the session that ran before it is unaffected.
    with (
        mock.patch.object(settings, "ENVIRONMENT", "production"),
        mock.patch.object(
            auth_module,
            "AsyncSessionLocal",
            _StubSessionFactory(_StubRow()),
        ),
    ):
        assert _login(client, "observer", dev_test_password) == status.HTTP_401_UNAUTHORIZED

    assert _me(client, token) == status.HTTP_200_OK
    assert _logout(client, token) == status.HTTP_200_OK
    assert _me(client, token) == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_an_expired_token_is_refused(client: TestClient) -> None:
    """A token whose `exp` is in the past is refused at every path."""
    payload = {
        "sub": "observer",
        "role": "OBSERVER",
        "exp": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1),
    }
    expired_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    assert _me(client, expired_token) == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_a_token_that_was_touched_is_refused(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """Every token reaches `decode_access_token`, including a touched one."""
    token = create_access_token("observer", UserRole.OBSERVER)
    session = create_user_session("observer", UserRole.OBSERVER)
    assert session.username == "observer"
    assert _me(client, token) == status.HTTP_200_OK

    touched = token[:-5] + ("0" * 5)
    assert _me(client, touched) == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_a_token_without_a_token_identity_is_accepted_until_it_expires(
    client: TestClient,
) -> None:
    """A token that predates the token identity cannot be revoked.

    The platform cannot name such a token, so it accepts it until it expires
    and says so in the log. The limitation is stated rather than hidden.
    """
    legacy = _token_without_identity()

    assert _me(client, legacy) == status.HTTP_200_OK

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {legacy}"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert "cannot be revoked" in response.json()["message"]
    assert _me(client, legacy) == status.HTTP_200_OK
