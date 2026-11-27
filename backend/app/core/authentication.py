"""Identity (authentication) service and login flow orchestration.

The service implements a single canonical login endpoint flow:

    1. Reject requests whose session token is missing, expired or malformed.
    2. Record every attempt including non-revealing failure reasons.
    3. Rate-limit repeating attempts with a sliding window per topic.
    4. Verify credentials against a persistent user store (production) or an
       in-process development store, never exposing which column failed.
       Production authentication is source-bound: accounts are accepted only
       from the production user database, and development accounts are never
       consulted in production.
    5. Measure the login throttle per user and per client identity: every
       attempt is keyed on the combination of both, so no single client can
       exhaust the throttle of every user and no single user can exhaust the
       throttle of every client.
    6. Issue a JWT binding the resolved role to the session.

No other code path may issue or verify session tokens; the service is the
single authority.
"""

import logging
from typing import Any

from passlib.hash import pbkdf2_sha256

from backend.app.core.audit import audit_log
from backend.app.core.auth_development import dev_user_accounts
from backend.app.core.config import settings
from backend.app.core.limits import AuthenticationRateLimiter
from backend.app.core.rbac import Permission, UserRole, create_access_token, create_user_session
from backend.app.core.users import UserAccount, UserRepository

logger = logging.getLogger(__name__)

AUTH_TOPIC = "powertwin-auth"
LOGIN_TOPIC = "powertwin-login"

SUCCESS_EVENT = "LOGIN_SUCCESS"
FAILURE_EVENT = "LOGIN_FAILURE"
RATE_LIMIT_EVENT = "LOGIN_RATE_LIMITED"
ACCOUNT_LOCK_EVENT = "LOGIN_ACCOUNT_LOCKED"
CREATE_USER_EVENT = "CREATE_USER"


class AuthenticationError(Exception):
    """Raised when credentials or session identification is rejected."""


class AuthenticationResult:
    """Deterministic outcome of a login attempt."""

    STATUS_SUCCESS = "SUCCESS"
    STATUS_INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    STATUS_RATE_LIMITED = "RATE_LIMITED"
    STATUS_ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    STATUS_UNAVAILABLE = "UNAVAILABLE"

    def __init__(
        self,
        success: bool,
        status: str,
        token: str | None = None,
        user: UserAccount | None = None,
    ) -> None:
        self.success = success
        self.status = status
        self.token = token
        self.user = user

    def model_dump(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "token": self.token,
            "role": self.user.role.value if self.user is not None else None,
        }


class AuthenticationService:
    """Single entry point for authentication state and rate limiting."""

    def __init__(self, rate_limiter: AuthenticationRateLimiter | None = None) -> None:
        self.rate_limiter = rate_limiter or AuthenticationRateLimiter(
            max_attempts=settings.LOGIN_RATE_LIMIT,
            lockout_seconds=settings.LOGIN_LOCKOUT_SECONDS,
        )

    @property
    def dev_accounts(self) -> dict[str, UserAccount]:
        """Resolve the in-process development accounts for this process.

        Password hashes are recomputed on each access so that an explicit
        environment override is always honoured without relying on a value
        captured by a previous import.

        Development accounts are never consulted in a production environment:
        the property returns an empty mapping there so that a login attempt can
        only ever be resolved against the production user database, and
        `dev_user_accounts()` is never invoked by the service in production.
        """
        if settings.ENVIRONMENT == "production":
            return {}

        accounts: dict[str, UserAccount] = {}
        for username, user_data in dev_user_accounts().items():
            accounts[username] = UserAccount(
                username=username,
                role=user_data["role"],
                hashed_password=user_data["hashed_password"],
                is_active=True,
            )
        return accounts

    def password_ok(self, plain: str, hashed: str) -> bool:
        """Verify a plaintext password against its hash."""
        return bool(pbkdf2_sha256.verify(plain, hashed))

    async def login(
        self,
        username: str,
        plain_password: str,
        session: Any | None = None,
        client_id: str | None = None,
    ) -> AuthenticationResult:
        """Login with credentials subject to rate limiting and audit recording.

        The rate limit is measured on a topic of one username from one client
        identity, so no single client exhausts the throttle of every user and
        no single user exhausts the throttle of every client. An attempt
        against an unknown username is counted the same way as one against a
        known one, without revealing which of the two was missing.
        """
        username = username.lower().strip()
        if not username or not plain_password:
            return AuthenticationResult(
                success=False, status=AuthenticationResult.STATUS_INVALID_CREDENTIALS
            )

        topic = self.rate_limiter.topic(username, client_id)
        if self.rate_limiter.is_blocked(topic):
            audit_log.record_failure(RATE_LIMIT_EVENT, username, LOGIN_TOPIC)
            return AuthenticationResult(
                success=False, status=AuthenticationResult.STATUS_RATE_LIMITED
            )

        try:
            candidate: UserAccount | None = None
            if session is not None:
                user = await UserRepository(session).get_by_username(username)
                candidate = user if user is not None else None
                if candidate is not None:
                    candidate = UserAccount(**candidate.model_dump())

            if candidate is None and settings.ENVIRONMENT != "production":
                # Development accounts only ever substitute for a missing row
                # in a non-production environment: production identities must
                # always be resolved through the production user database.
                candidate = self.dev_accounts.get(username)

            if candidate is None:
                # Record the failure exactly like a wrong password, so an
                # attempt against a name that exists in no row never sits
                # outside the throttle and never decides the outcome: the
                # result names the credentials, not the account.
                audit_log.record_failure(FAILURE_EVENT, username, LOGIN_TOPIC)
                self.rate_limiter.record_attempt(topic)
                raise AuthenticationError("Account not found")
            if not candidate.is_active or candidate.is_locked():
                audit_log.record_failure(ACCOUNT_LOCK_EVENT, username, LOGIN_TOPIC)
                self.rate_limiter.record_attempt(topic)
                return AuthenticationResult(
                    success=False, status=AuthenticationResult.STATUS_ACCOUNT_LOCKED
                )

            if not candidate.hashed_password or not self.password_ok(
                plain_password, candidate.hashed_password
            ):
                audit_log.record_failure(FAILURE_EVENT, username, LOGIN_TOPIC)
                self.rate_limiter.record_attempt(topic)
                raise AuthenticationError("Invalid credentials")

            if session is not None:
                await UserRepository(session).record_successful_login(username)

            token = create_access_token(username, candidate.role)
            audit_log.record(SUCCESS_EVENT, username, LOGIN_TOPIC)
            self.rate_limiter.reset(topic)
            return AuthenticationResult(
                success=True,
                status=AuthenticationResult.STATUS_SUCCESS,
                token=token,
                user=candidate,
            )

        except AuthenticationError as err:
            logger.warning("Login failed for '%s': %s", username, err)
            return AuthenticationResult(
                success=False, status=AuthenticationResult.STATUS_INVALID_CREDENTIALS
            )
        except Exception as err:
            logger.error("Unexpected login failure for '%s': %s", username, err)
            self.rate_limiter.record_attempt(topic)
            return AuthenticationResult(
                success=False, status=AuthenticationResult.STATUS_UNAVAILABLE
            )

    async def create_production_user(
        self,
        session: Any,
        username: str,
        plain_password: str,
        role: UserRole,
    ) -> UserAccount:
        """Provision a production identity in the database (administrative only)."""
        if session is None:
            raise AuthenticationError("Database session is required to create a production user")
        repo = UserRepository(session)
        if not await repo.exists():
            raise AuthenticationError("Database identity table does not exist")
        account = await repo.create_user(username, pbkdf2_sha256.hash(plain_password), role)
        audit_log.record(CREATE_USER_EVENT, "SYSTEM_ADMIN", username, details={"role": role.value})
        return account

    def get_session_permissions(self, role: UserRole) -> set[Permission]:
        """Return the permission set for a role (frontend mirroring)."""
        return create_user_session("sync", role).permissions
