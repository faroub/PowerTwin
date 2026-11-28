"""User identity persistence and authentication operations.

Production identities live in the relational database and are provisioned by
the administration seeding script (`scripts/seed_users.py`); nothing is hard
coded here. Development-only accounts are initialised at startup and kept in a
per-process in-memory store when no database connection is available.

The repository never performs database I/O from the synchronous event loop and
never blocks the application while waiting on a database that is unreachable.
"""

import datetime
import logging
from typing import Any

from sqlalchemy import select

from backend.app.core.rbac import UserRole
from backend.app.historian.models import UserAccountModel

logger = logging.getLogger(__name__)


class UserAccount:
    """In-memory representation of a user account row."""

    def __init__(
        self,
        username: str,
        role: UserRole | str,
        hashed_password: str,
        is_active: bool = True,
        last_login_at: datetime.datetime | None = None,
        failed_login_attempts: int = 0,
        locked_until: datetime.datetime | None = None,
        **kwargs: Any,
    ) -> None:
        self.username = username
        # A row carries the role as the string the database stores, while the
        # platform carries it as the enumeration every permission table is
        # written against. The role is resolved here, once, so that a row
        # read from the database and an account built in the process are the
        # same kind of object. A role the platform does not know is refused
        # here rather than carried further.
        self.role = UserRole(role)
        self.hashed_password = hashed_password
        self.is_active = is_active
        self.last_login_at = last_login_at
        self.failed_login_attempts = failed_login_attempts
        self.locked_until = locked_until

    def is_locked(self) -> bool:
        """Return whether the account is currently subject to a login lockout."""
        if self.locked_until is None:
            return False
        return datetime.datetime.now(datetime.UTC) < self.locked_until

    def model_dump(self) -> dict[str, Any]:
        """Serialize the account record with explicit schema typing."""
        return {
            "username": self.username,
            "role": self.role.value,
            "hashed_password": self.hashed_password,
            "is_active": self.is_active,
            "last_login_at": self.last_login_at,
            "failed_login_attempts": self.failed_login_attempts,
            "locked_until": self.locked_until,
        }


class UserRepository:
    """Database-backed lookup and persistence of user accounts."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> UserAccount | None:
        """Load a single account by username, or None when it does not exist."""
        try:
            result = await self._session.execute(
                select(UserAccountModel).where(UserAccountModel.username == username)
            )
        except Exception as e:
            logger.warning("Failed to load the user account '%s': %s", username, e)
            return None

        row = result.scalar_one_or_none()
        if row is None:
            return None
        return UserAccount(**self._row_to_dict(row))

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """Convert a row to a keyword-safe dictionary."""
        return {
            "id": row.id,
            "username": row.username,
            "hashed_password": row.hashed_password,
            "role": row.role,
            "is_active": row.is_active,
            "created_at": row.created_at,
            "last_login_at": row.last_login_at,
            "failed_login_attempts": row.failed_login_attempts,
            "locked_until": row.locked_until,
        }

    async def exists(self) -> bool:
        """Return whether the identity table contains at least one account."""
        try:
            result = await self._session.execute(select(UserAccountModel.id).limit(1))
        except Exception as e:
            logger.warning("Failed to read the identity table for seeding checks: %s", e)
            return False
        return result.scalar_one_or_none() is not None

    async def create_user(self, username: str, hashed_password: str, role: UserRole) -> UserAccount:
        """Create a new identity record. Identifier collisions raise ValueError."""
        user = UserAccountModel(
            username=username,
            hashed_password=hashed_password,
            role=role.value,
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self._session.add(user)
        try:
            await self._session.commit()
            await self._session.refresh(user)
        except Exception as e:
            await self._session.rollback()
            if "unique" in str(e).lower():
                raise ValueError(f"User account '{username}' already exists") from e
            logger.warning("Failed to persist the '%s' account: %s", username, e)
            raise
        return UserAccount(**self._row_to_dict(user))

    async def record_failed_login(self, username: str, lockout_minutes: int) -> UserAccount:
        """Increment the failed attempt counter and lock the account if required."""
        try:
            result = await self._session.execute(
                select(UserAccountModel).where(UserAccountModel.username == username)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return _placeholder(username, lockout_minutes)
            row.failed_login_attempts += 1
            row.locked_until = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                minutes=lockout_minutes
            )
            await self._session.commit()
        except Exception as e:
            logger.warning("Failed to record the failed login of '%s': %s", username, e)
            return _placeholder(username, lockout_minutes)
        return UserAccount(**self._row_to_dict(row))

    async def record_successful_login(self, username: str) -> UserAccount:
        """Clear the attempt counters and record the last login time."""
        try:
            result = await self._session.execute(
                select(UserAccountModel).where(UserAccountModel.username == username)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return _placeholder(username, 0)
            row.failed_login_attempts = 0
            row.locked_until = None
            row.last_login_at = datetime.datetime.now(datetime.UTC)
            await self._session.commit()
        except Exception as e:
            logger.warning("Failed to record the successful login of '%s': %s", username, e)
        return UserAccount(**self._row_to_dict(row))


def _placeholder(username: str, lockout_minutes: int) -> UserAccount:
    """Return a placeholder account for rows that did not survive row lookup."""
    return UserAccount(username=username, role=UserRole.OBSERVER, hashed_password="")


async def get_root_administrator(session: Any) -> UserAccount | None:
    """Return the currently provisioned administrator account, if any."""
    repo = UserRepository(session)
    try:
        result = await repo._session.execute(
            select(UserAccountModel).where(UserAccountModel.role == "ADMINISTRATOR").limit(1)
        )
    except Exception as e:
        logger.warning("Failed to read the administrator account: %s", e)
        return None
    row = result.scalar_one_or_none()
    return None if row is None else UserAccount(**repo._row_to_dict(row))
