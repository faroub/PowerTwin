"""Server-side revocation of the session tokens the platform issues.

The platform issues stateless JWTs: a token carries the identity of the
account that holds it, and it is validated on its signature and on its expiry.
That contract alone cannot answer the question a logout asks — *may this token
still be used?* — because the token carries no identity the platform can name:
the platform never stored one.

The schema that answers it already exists. Migration ``003_revoked_tokens``
creates the ``revoked_tokens`` table and ``RevokedTokenModel`` maps it; the
two agree column for column. What was missing was the code: the tokens
carried no ``jti`` claim, nothing ever wrote a row, and nothing ever read one
back. This module is that code, and it needs no further schema.

Two stores implement the same contract:

* :class:`InMemoryRevocationStore` — the local-development store. It holds
  the revocations in the process, which is enough for the single-process
  local platform and keeps a development environment free of a database
  dependency;
* :class:`DatabaseRevocationStore` — the production store. It persists the
  revocations in the ``revoked_tokens`` table, so a revoked token stays
  revoked across processes, restarts and deployments.

The environment decides which store answers, never the caller: production
reads and writes the database, every other environment reads and writes the
in-process store. Neither store ever falls back to the other. A store that
cannot answer says so, and the caller refuses the request rather than
accepting a token it could not check.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import delete, func, select

from backend.app.core.config import settings
from backend.app.historian.db import AsyncSessionLocal
from backend.app.historian.models import RevokedTokenModel

logger = logging.getLogger(__name__)

__all__ = [
    "REVOCATION_REASON_LOGOUT",
    "DatabaseRevocationStore",
    "InMemoryRevocationStore",
    "Revocation",
    "RevocationStore",
    "RevocationStoreUnavailableError",
    "get_revocation_store",
    "is_token_revoked",
    "purge_expired_revocations",
    "reset_development_store",
    "revoke_token",
]

#: The reason a token is revoked today: the owner of the session ended it.
#: The column records the reason next to the revocation, so an operator can
#: tell a voluntary logout from any other cause the platform may add later.
#: Only the logout is implemented — the platform has no user-deactivation or
#: administrative-revocation operation, and no reason is declared for an
#: operation that does not exist.
REVOCATION_REASON_LOGOUT = "LOGOUT"


class RevocationStoreUnavailableError(Exception):
    """Raised when a revocation store could not answer a question."""


@dataclass(frozen=True)
class Revocation:
    """One recorded revocation.

    Attributes:
        token_id: The ``jti`` claim of the revoked token.
        subject: The account that held the token.
        expires_at: The expiry the token carries. The revocation is meaningless
            after that moment, which is when the row may be purged.
        reason: Why the token was revoked.
    """

    token_id: str
    subject: str
    expires_at: datetime.datetime
    reason: str


class RevocationStore(Protocol):
    """The contract every revocation store honours."""

    async def is_revoked(self, token_id: str) -> bool:
        """Return whether the token with the given identity has been revoked."""
        ...

    async def revoke(
        self,
        token_id: str,
        subject: str,
        expires_at: datetime.datetime,
        reason: str,
    ) -> None:
        """Record the revocation of a token."""
        ...

    async def purge_expired(self) -> int:
        """Forget the revocations whose token has expired, and return how many."""
        ...


class InMemoryRevocationStore:
    """Revocations held in the process, for development and testing.

    The store keeps the revocations of one process only. It is therefore the
    store of a local development environment, where a single process serves
    the platform and a restart ends every session anyway. It is never the
    store of a production deployment: a revocation recorded in one worker
    would be invisible to the others.
    """

    def __init__(self) -> None:
        self._revoked: dict[str, Revocation] = {}

    async def is_revoked(self, token_id: str) -> bool:
        """Return whether the token with the given identity has been revoked."""
        revocation = self._revoked.get(token_id)
        if revocation is None:
            return False
        if revocation.expires_at <= datetime.datetime.now(datetime.UTC):
            # The token expired by itself; the revocation no longer says
            # anything the expiry does not already say.
            self._revoked.pop(token_id, None)
            return False
        return True

    async def revoke(
        self,
        token_id: str,
        subject: str,
        expires_at: datetime.datetime,
        reason: str,
    ) -> None:
        """Record the revocation of a token."""
        self._revoked[token_id] = Revocation(
            token_id=token_id,
            subject=subject,
            expires_at=expires_at,
            reason=reason,
        )

    async def purge_expired(self) -> int:
        """Forget the revocations whose token has expired, and return how many."""
        now = datetime.datetime.now(datetime.UTC)
        stale = [
            token_id
            for token_id, revocation in self._revoked.items()
            if revocation.expires_at <= now
        ]
        for token_id in stale:
            self._revoked.pop(token_id, None)
        return len(stale)

    def clear(self) -> None:
        """Forget every revocation recorded in this store."""
        self._revoked.clear()


class DatabaseRevocationStore:
    """Revocations persisted in the ``revoked_tokens`` table.

    The table is the one migration ``003_revoked_tokens`` creates and the one
    ``RevokedTokenModel`` maps, so a revoked token stays revoked across
    processes, restarts and deployments.

    Every call opens its own session: the store is used from a request
    dependency that must not hold a transaction open between requests.
    """

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    async def is_revoked(self, token_id: str) -> bool:
        """Return whether the token with the given identity has been revoked."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(RevokedTokenModel.jti).where(RevokedTokenModel.jti == token_id)
            )
            return result.scalar_one_or_none() is not None

    async def revoke(
        self,
        token_id: str,
        subject: str,
        expires_at: datetime.datetime,
        reason: str,
    ) -> None:
        """Record the revocation of a token."""
        async with self._session_factory() as session:
            session.add(
                RevokedTokenModel(
                    jti=token_id,
                    sub=subject,
                    expires_at=expires_at,
                    reason=reason,
                )
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def purge_expired(self) -> int:
        """Forget the revocations whose token has expired, and return how many.

        The comparison is made by the database (``now()``), not by Python, so
        the statement reads the same on every dialect and compares the stored
        expiry against the database's own clock.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                delete(RevokedTokenModel).where(RevokedTokenModel.expires_at < func.now())
            )
            await session.commit()
            return int(result.rowcount or 0)


#: The store of a development or testing environment. It is a module-level
#: object because the revocations of a process outlive the request that
#: recorded them.
_development_store = InMemoryRevocationStore()


def get_revocation_store() -> RevocationStore:
    """Return the revocation store of the current environment.

    Production reads and writes the database; every other environment reads
    and writes the in-process store. The choice is made from the environment
    alone, never from the request.
    """
    if settings.ENVIRONMENT == "production":
        return DatabaseRevocationStore(AsyncSessionLocal)
    return _development_store


def reset_development_store() -> None:
    """Forget every revocation recorded in the development store."""
    _development_store.clear()


async def is_token_revoked(token_id: str) -> bool:
    """Return whether the token with the given identity has been revoked.

    Raises:
        RevocationStoreUnavailableError: When the store could not answer. The
            caller must refuse the token rather than accept a token it could
            not check.
    """
    store = get_revocation_store()
    try:
        return await store.is_revoked(token_id)
    except Exception as err:
        raise RevocationStoreUnavailableError(str(err)) from err


async def revoke_token(
    token_id: str,
    subject: str,
    expires_at: datetime.datetime,
    reason: str,
) -> None:
    """Record the revocation of a token.

    Raises:
        RevocationStoreUnavailableError: When the store could not record the
            revocation. The caller must say that the session was not
            terminated rather than pretend it was.
    """
    store = get_revocation_store()
    try:
        await store.revoke(token_id, subject, expires_at, reason)
    except Exception as err:
        raise RevocationStoreUnavailableError(str(err)) from err


async def purge_expired_revocations() -> int:
    """Forget the revocations whose token has expired, and return how many.

    A failed purge is a maintenance failure, not a session failure: it is
    logged and reported, and the caller carries on.
    """
    store = get_revocation_store()
    try:
        return await store.purge_expired()
    except Exception as err:
        logger.warning("The expired token revocations could not be purged: %s", err)
        return 0
