"""Tests for the server-side revocation of the session tokens.

The platform issues stateless JWTs that carry a unique identity (``jti``). A
logout records that identity in the revocation store of the environment, and
every protected route refuses a token the store names. The store is the
database in production and the process itself in development; neither ever
falls back to the other, and a store that cannot answer refuses the request
rather than accepting a token it could not check.

The database tests run against a **real SQL database** — SQLite through the
standard-library driver — so the statements the store issues are executed, not
mocked. The backend has no asynchronous SQLite driver, so the synchronous
session is served behind the asynchronous protocol the store speaks.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from typing import Any
from unittest import mock

import jwt
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from passlib.hash import pbkdf2_sha256
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.v1 import auth as auth_module
from backend.app.core import revocation as revocation_module
from backend.app.core.config import settings
from backend.app.core.rbac import decode_access_token
from backend.app.core.revocation import (
    DatabaseRevocationStore,
    InMemoryRevocationStore,
    RevocationStoreUnavailableError,
    get_revocation_store,
    is_token_revoked,
    purge_expired_revocations,
    revoke_token,
)
from backend.app.historian.models import RevokedTokenModel, UserAccountModel


class _AsyncSession:
    """The asynchronous protocol of a session, served by a synchronous session.

    The store and the identity repository only ever await `execute`,
    `commit`, `rollback` and `refresh`, and only ever call `add` directly.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: Any) -> Any:
        return self._session.execute(statement)

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def refresh(self, instance: Any) -> None:
        self._session.refresh(instance)

    def add(self, instance: Any) -> None:
        self._session.add(instance)


class _AsyncSessionContext:
    """The asynchronous context manager the store opens a session with."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def __aenter__(self) -> _AsyncSession:
        return _AsyncSession(self._session)

    async def __aexit__(self, *_exc: Any) -> None:
        return None


class _AsyncSessionFactory:
    """A session factory that hands out an adapter over one SQL session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def __call__(self) -> _AsyncSessionContext:
        return _AsyncSessionContext(self._session)


class _BrokenStore:
    """A revocation store that cannot answer."""

    async def is_revoked(self, _token_id: str) -> bool:
        raise RuntimeError("the revocation database is unreachable")

    async def revoke(self, *_args: Any) -> None:
        raise RuntimeError("the revocation database is unreachable")

    async def purge_expired(self) -> int:
        raise RuntimeError("the revocation database is unreachable")


class _UnwritableStore(_BrokenStore):
    """A revocation store that answers a question but cannot record a revocation."""

    async def is_revoked(self, _token_id: str) -> bool:
        return False


@pytest.fixture
def sql_database() -> Iterator[tuple[Session, _AsyncSessionFactory]]:
    """A real SQL database holding the identity and revocation tables."""
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    UserAccountModel.__table__.create(engine)
    RevokedTokenModel.__table__.create(engine)
    session = Session(engine)
    try:
        yield session, _AsyncSessionFactory(session)
    finally:
        session.close()
        engine.dispose()


def _add_user(session: Session, username: str = "operator", password: str = "pw_for_tests") -> None:
    """Provision one active account in the identity table."""
    session.add(
        UserAccountModel(
            username=username,
            hashed_password=pbkdf2_sha256.hash(password),
            role="OBSERVER",
            is_active=True,
        )
    )
    session.commit()


def _login(client: TestClient, username: str = "observer", password: str = "") -> str:
    """Log in and return the access token."""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return str(response.json()["access_token"])


def _me(client: TestClient, token: str) -> Any:
    """Return the answer of an authenticated read of the session profile."""
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


def _logout(client: TestClient, token: str) -> Any:
    """Return the answer of a logout performed with ``token``."""
    return client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})


class TestInMemoryStore:
    """The store of a local development environment."""

    @pytest.mark.asyncio
    async def test_a_revoked_token_is_reported_as_revoked(self) -> None:
        store = InMemoryRevocationStore()
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=60)

        await store.revoke("token-1", "observer", expires_at, "LOGOUT")

        assert await store.is_revoked("token-1") is True
        assert await store.is_revoked("token-2") is False

    @pytest.mark.asyncio
    async def test_a_revocation_of_an_expired_token_is_forgotten(self) -> None:
        store = InMemoryRevocationStore()
        expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)

        await store.revoke("token-1", "observer", expires_at, "LOGOUT")

        # The token expired by itself, so the revocation says nothing the
        # expiry does not already say.
        assert await store.is_revoked("token-1") is False
        assert await store.purge_expired() == 0

    @pytest.mark.asyncio
    async def test_the_purge_forgets_the_expired_revocations_only(self) -> None:
        store = InMemoryRevocationStore()
        now = datetime.datetime.now(datetime.UTC)

        await store.revoke("expired", "observer", now - datetime.timedelta(seconds=1), "LOGOUT")
        await store.revoke("live", "observer", now + datetime.timedelta(minutes=60), "LOGOUT")

        assert await store.purge_expired() == 1
        assert await store.is_revoked("live") is True
        assert await store.is_revoked("expired") is False

    @pytest.mark.asyncio
    async def test_the_store_can_be_emptied(self) -> None:
        store = InMemoryRevocationStore()
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=60)

        await store.revoke("token-1", "observer", expires_at, "LOGOUT")
        store.clear()

        assert await store.is_revoked("token-1") is False


class TestDatabaseStore:
    """The store of a production deployment, against a real SQL database."""

    @pytest.mark.asyncio
    async def test_a_revocation_is_persisted_and_read_back(
        self, sql_database: tuple[Session, _AsyncSessionFactory]
    ) -> None:
        _session, factory = sql_database
        store = DatabaseRevocationStore(factory)
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=60)

        await store.revoke("token-1", "observer", expires_at, "LOGOUT")

        # A second store, as a second process would hold it, reads the row.
        other = DatabaseRevocationStore(factory)
        assert await other.is_revoked("token-1") is True
        assert await other.is_revoked("token-2") is False

    @pytest.mark.asyncio
    async def test_the_row_carries_the_account_the_expiry_and_the_reason(
        self, sql_database: tuple[Session, _AsyncSessionFactory]
    ) -> None:
        session, factory = sql_database
        store = DatabaseRevocationStore(factory)
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=60)

        await store.revoke("token-1", "observer", expires_at, "LOGOUT")

        row = session.execute(select(RevokedTokenModel)).scalar_one()
        assert row.jti == "token-1"
        assert row.sub == "observer"
        assert row.reason == "LOGOUT"
        assert row.expires_at is not None

    @pytest.mark.asyncio
    async def test_the_purge_removes_the_expired_rows_only(
        self, sql_database: tuple[Session, _AsyncSessionFactory]
    ) -> None:
        session, factory = sql_database
        store = DatabaseRevocationStore(factory)
        now = datetime.datetime.now(datetime.UTC)

        await store.revoke("expired", "observer", now - datetime.timedelta(minutes=1), "LOGOUT")
        await store.revoke("live", "observer", now + datetime.timedelta(minutes=60), "LOGOUT")

        assert await store.purge_expired() == 1
        remaining = session.execute(select(RevokedTokenModel.jti)).scalars().all()
        assert list(remaining) == ["live"]

    @pytest.mark.asyncio
    async def test_a_failing_store_is_reported_as_unavailable(
        self, sql_database: tuple[Session, _AsyncSessionFactory]
    ) -> None:
        session, factory = sql_database

        # The table is gone: the statements of the store fail, and the
        # platform is told that it could not check the token.
        RevokedTokenModel.__table__.drop(session.get_bind())

        with (
            mock.patch.object(settings, "ENVIRONMENT", "production"),
            mock.patch.object(revocation_module, "AsyncSessionLocal", factory),
        ):
            with pytest.raises(RevocationStoreUnavailableError):
                await is_token_revoked("token-1")


class TestStoreSelection:
    """The environment decides which store answers, never the caller."""

    def test_production_uses_the_database(self) -> None:
        with mock.patch.object(settings, "ENVIRONMENT", "production"):
            assert isinstance(get_revocation_store(), DatabaseRevocationStore)

    @pytest.mark.parametrize("environment", ["development", "testing"])
    def test_every_other_environment_uses_the_process(self, environment: str) -> None:
        with mock.patch.object(settings, "ENVIRONMENT", environment):
            assert isinstance(get_revocation_store(), InMemoryRevocationStore)

    @pytest.mark.asyncio
    async def test_a_failing_store_never_falls_back_to_the_other_one(self) -> None:
        with (
            mock.patch.object(settings, "ENVIRONMENT", "production"),
            mock.patch.object(revocation_module, "AsyncSessionLocal", None),
        ):
            # The production store cannot answer, and the platform does not
            # fall back to the in-process store to answer in its place.
            with pytest.raises(RevocationStoreUnavailableError):
                await is_token_revoked("token-1")


class TestLocalDevelopmentLogout:
    """The logout of a local development environment."""

    @pytest.mark.asyncio
    async def test_the_token_of_the_caller_is_refused_after_the_logout(
        self, client: TestClient, dev_test_password: str
    ) -> None:
        token = _login(client, "observer", dev_test_password)
        assert _me(client, token).status_code == status.HTTP_200_OK

        assert _logout(client, token).status_code == status.HTTP_200_OK

        refused = _me(client, token)
        assert refused.status_code == status.HTTP_401_UNAUTHORIZED
        assert "revoked" in refused.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_the_other_tokens_of_the_account_keep_working(
        self, client: TestClient, dev_test_password: str
    ) -> None:
        first = _login(client, "observer", dev_test_password)
        second = _login(client, "observer", dev_test_password)

        assert _logout(client, first).status_code == status.HTTP_200_OK

        assert _me(client, first).status_code == status.HTTP_401_UNAUTHORIZED
        assert _me(client, second).status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_the_revocation_is_recorded_for_the_token_that_was_used(
        self, client: TestClient, dev_test_password: str
    ) -> None:
        token = _login(client, "observer", dev_test_password)
        token_id = decode_access_token(token).token_id

        assert _logout(client, token).status_code == status.HTTP_200_OK

        assert await is_token_revoked(token_id) is True

    @pytest.mark.asyncio
    async def test_a_revoked_token_cannot_log_out_again(
        self, client: TestClient, dev_test_password: str
    ) -> None:
        token = _login(client, "observer", dev_test_password)
        assert _logout(client, token).status_code == status.HTTP_200_OK

        # The token is refused at the door, so the second logout never runs.
        assert _logout(client, token).status_code == status.HTTP_401_UNAUTHORIZED


class TestProductionLogout:
    """The logout of a production deployment, against a real SQL database."""

    @pytest.mark.asyncio
    async def test_the_logout_revokes_the_token_in_the_database(
        self,
        client: TestClient,
        sql_database: tuple[Session, _AsyncSessionFactory],
    ) -> None:
        session, factory = sql_database
        _add_user(session)

        with (
            mock.patch.object(settings, "ENVIRONMENT", "production"),
            mock.patch.object(auth_module, "AsyncSessionLocal", factory),
            mock.patch.object(revocation_module, "AsyncSessionLocal", factory),
        ):
            token = _login(client, "operator", "pw_for_tests")
            token_id = decode_access_token(token).token_id

            assert _me(client, token).status_code == status.HTTP_200_OK
            assert _logout(client, token).status_code == status.HTTP_200_OK

            # The token is refused from that moment on.
            refused = _me(client, token)
            assert refused.status_code == status.HTTP_401_UNAUTHORIZED
            assert "revoked" in refused.json()["detail"].lower()

        row = session.execute(select(RevokedTokenModel)).scalar_one()
        assert row.jti == token_id
        assert row.sub == "operator"
        assert row.reason == "LOGOUT"

    @pytest.mark.asyncio
    async def test_the_other_tokens_keep_working_after_one_logout(
        self,
        client: TestClient,
        sql_database: tuple[Session, _AsyncSessionFactory],
    ) -> None:
        session, factory = sql_database
        _add_user(session)

        with (
            mock.patch.object(settings, "ENVIRONMENT", "production"),
            mock.patch.object(auth_module, "AsyncSessionLocal", factory),
            mock.patch.object(revocation_module, "AsyncSessionLocal", factory),
        ):
            first = _login(client, "operator", "pw_for_tests")
            second = _login(client, "operator", "pw_for_tests")

            assert _logout(client, first).status_code == status.HTTP_200_OK

            assert _me(client, first).status_code == status.HTTP_401_UNAUTHORIZED
            assert _me(client, second).status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_a_revocation_survives_the_loss_of_the_process(
        self,
        client: TestClient,
        sql_database: tuple[Session, _AsyncSessionFactory],
    ) -> None:
        session, factory = sql_database
        _add_user(session)

        with (
            mock.patch.object(settings, "ENVIRONMENT", "production"),
            mock.patch.object(auth_module, "AsyncSessionLocal", factory),
            mock.patch.object(revocation_module, "AsyncSessionLocal", factory),
        ):
            token = _login(client, "operator", "pw_for_tests")
            token_id = decode_access_token(token).token_id
            assert _logout(client, token).status_code == status.HTTP_200_OK

        # A later process reads the row and refuses the token.
        with (
            mock.patch.object(settings, "ENVIRONMENT", "production"),
            mock.patch.object(revocation_module, "AsyncSessionLocal", factory),
        ):
            assert await is_token_revoked(token_id) is True
            assert _me(client, token).status_code == status.HTTP_401_UNAUTHORIZED


class TestTokensWithoutATokenIdentity:
    """A token that was issued before the platform issued token identities."""

    @pytest.mark.asyncio
    async def test_it_is_accepted_until_it_expires(self, client: TestClient) -> None:
        legacy = _token_without_identity()

        assert decode_access_token(legacy).token_id == ""
        assert _me(client, legacy).status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_the_logout_says_that_it_cannot_be_revoked(self, client: TestClient) -> None:
        legacy = _token_without_identity()

        response = _logout(client, legacy)

        assert response.status_code == status.HTTP_200_OK
        assert "cannot be revoked" in response.json()["message"]
        # The token keeps working until it expires: the platform cannot name
        # it, and it says so rather than pretending otherwise.
        assert _me(client, legacy).status_code == status.HTTP_200_OK


class TestFailClosed:
    """A store that cannot answer refuses the request."""

    @pytest.mark.asyncio
    async def test_production_refuses_a_token_it_could_not_check(
        self, client: TestClient, dev_test_password: str
    ) -> None:
        token = _login(client, "observer", dev_test_password)

        with (
            mock.patch.object(settings, "ENVIRONMENT", "production"),
            mock.patch.object(revocation_module, "get_revocation_store", lambda: _BrokenStore()),
        ):
            response = _me(client, token)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_development_refuses_a_token_it_could_not_check(
        self, client: TestClient, dev_test_password: str
    ) -> None:
        token = _login(client, "observer", dev_test_password)

        with mock.patch.object(revocation_module, "get_revocation_store", lambda: _BrokenStore()):
            response = _me(client, token)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_a_logout_that_cannot_record_the_revocation_fails(
        self, client: TestClient, dev_test_password: str
    ) -> None:
        token = _login(client, "observer", dev_test_password)

        # The store answers the question about the token but cannot record the
        # revocation: the request reaches the logout endpoint.
        with mock.patch.object(
            revocation_module, "get_revocation_store", lambda: _UnwritableStore()
        ):
            response = _logout(client, token)

        # The session was not terminated, and the endpoint says so instead of
        # answering as if it had been.
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_a_logout_in_production_that_cannot_record_the_revocation_fails(
        self, client: TestClient, dev_test_password: str
    ) -> None:
        token = _login(client, "observer", dev_test_password)

        with (
            mock.patch.object(settings, "ENVIRONMENT", "production"),
            mock.patch.object(
                revocation_module, "get_revocation_store", lambda: _UnwritableStore()
            ),
        ):
            response = _logout(client, token)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_a_purge_that_fails_is_not_a_session_failure(self) -> None:
        with mock.patch.object(revocation_module, "get_revocation_store", lambda: _BrokenStore()):
            assert await purge_expired_revocations() == 0

    @pytest.mark.asyncio
    async def test_a_revocation_that_cannot_be_recorded_is_reported(
        self, client: TestClient, dev_test_password: str
    ) -> None:
        with mock.patch.object(revocation_module, "get_revocation_store", lambda: _BrokenStore()):
            with pytest.raises(RevocationStoreUnavailableError):
                await revoke_token(
                    "token-1",
                    "observer",
                    datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=60),
                    "LOGOUT",
                )


def _token_without_identity() -> str:
    """Return a token that carries no ``jti`` claim."""
    payload = {
        "sub": "observer",
        "role": "OBSERVER",
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=60),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
