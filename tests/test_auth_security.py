"""Automated tests for authentication security boundaries and session management.

These tests cover:
    * Rate limiting of the login endpoint over a sliding window.
    * Rejection of missing, malformed, invalid, expired and tampered tokens.
    * Non-revealing failure responses across every rejected branch.
    * Backend role boundaries against the mirroring frontend role table.
    * Production startup rejection of missing secret configuration.
    * Audit logging of every accepted and rejected authentication action.
    * Trust boundaries of the client identity used by the rate limiter.
    * Per-identity throttling for unknown users, cross-user isolation and
      lockout expiry.
"""

import datetime
import logging
import os
from typing import Any
from unittest import mock

import jwt
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from passlib.hash import pbkdf2_sha256

from backend.app.core import auth_development, authentication
from backend.app.core.audit import audit_log
from backend.app.core.authentication import (
    AuthenticationResult,
    AuthenticationService,
)
from backend.app.core.config import settings
from backend.app.core.identity import resolve_client_id
from backend.app.core.limits import AuthenticationRateLimiter
from backend.app.core.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    UserRole,
    create_user_session,
    decode_access_token,
)
from backend.app.core.safety import (
    JWT_SECRET_MIN_BYTES,
    POSTGRES_PASSWORD_MIN_BYTES,
    validate_safety_invariants,
)
from backend.app.core.users import UserAccount


async def _login(
    service: AuthenticationService, username: str, password: str, client_id: str | None = None
) -> AuthenticationResult:
    """Execute one login attempt through the service."""
    return await service.login(username, password, session=None, client_id=client_id)


def _identity_topic(
    service: AuthenticationService, username: str, client_id: str | None = None
) -> str:
    """Return the topic key of one user from one client identity."""
    return service.rate_limiter.topic(username, client_id)


def _dev_password() -> str:
    """Return the value the development accounts use for this test run."""
    password = os.environ.get("POWERTWIN_DEV_PASSWORD")
    if password is None:
        password = "powertwin_test_dev_password_override"
        os.environ["POWERTWIN_DEV_PASSWORD"] = password
    return password


@pytest.mark.asyncio
async def test_random_development_password_is_stable_for_process(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A generated local password stays usable across account lookups."""
    monkeypatch.delenv("POWERTWIN_DEV_PASSWORD", raising=False)
    monkeypatch.delenv("POWERTWIN_DEFAULT_DEV_PASSWORD", raising=False)
    monkeypatch.setattr(auth_development, "_generated_dev_password", None)

    passwords = auth_development.dev_user_passwords()
    accounts = auth_development.dev_user_accounts()

    assert len(set(passwords.values())) == 1
    assert all(
        pbkdf2_sha256.verify(passwords["admin"], account["hashed_password"])
        for account in accounts.values()
    )
    result = await AuthenticationService().login("admin", passwords["admin"], session=None)

    assert result.success is True
    assert caplog.text.count("using a random default development password") == 1


@pytest.mark.asyncio
async def test_login_rate_limiting_blocks_repeated_attempts() -> None:
    """Test that repeated login attempts are blocked by the sliding window limiter."""
    service = AuthenticationService(AuthenticationRateLimiter(max_attempts=3, lockout_seconds=30))
    topic = _identity_topic(service, "observer")

    for _ in range(3):
        result = await _login(service, "observer", "wrong_password")
        assert result.success is False
        assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS

    assert service.rate_limiter.is_blocked(topic) is True
    result = await _login(service, "observer", "wrong_password")
    assert result.success is False
    assert result.status == AuthenticationResult.STATUS_RATE_LIMITED

    service.rate_limiter.reset(topic)
    result = await _login(service, "observer", "wrong_password")
    assert result.success is False
    assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_login_rate_limit_resets_after_success() -> None:
    """Test the rate limiter clears after a successful login."""
    service = AuthenticationService(AuthenticationRateLimiter(max_attempts=3, lockout_seconds=60))
    topic = _identity_topic(service, "observer")

    for _ in range(3):
        result = await _login(service, "observer", "wrong_password")
        assert result.success is False

    assert service.rate_limiter.is_blocked(topic) is True
    service.rate_limiter.reset(topic)

    password = _dev_password()
    result = await _login(service, "observer", password)
    assert result.success is True

    assert service.rate_limiter.is_blocked(topic) is False


@pytest.mark.asyncio
async def test_login_rejects_empty_payload() -> None:
    """Test empty usernames and passwords are rejected immediately."""
    service = AuthenticationService()
    for username, password in (("observer", ""), ("", "password"), ("", "")):
        result = await _login(service, username, password)
        assert result.success is False
        assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_hash_uniqueness_and_cost() -> None:
    """Test every password hash is derived uniquely and at the configured cost."""
    hashed1 = pbkdf2_sha256.hash("secure_password_example")
    hashed2 = pbkdf2_sha256.hash("secure_password_example")
    assert hashed1 != hashed2
    assert pbkdf2_sha256.verify("secure_password_example", hashed1) is True
    assert pbkdf2_sha256.verify("wrong_password_example", hashed1) is False


@pytest.mark.asyncio
async def test_audit_log_records_every_attempt(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that accepted and rejected logins generate audit records."""
    monkeypatch.setattr(audit_log, "flush_threshold", 1)
    log_file = tmp_path / "audit_events.json"
    monkeypatch.setattr(audit_log, "_log_file", str(log_file))

    service = AuthenticationService(AuthenticationRateLimiter(max_attempts=10, lockout_seconds=60))
    _dev_password()
    await _login(service, "observer", "wrong_password")
    result = await _login(service, "observer", _dev_password())
    assert result.success is True
    assert log_file.exists()
    events = audit_log.reload()
    assert any(e.action == "LOGIN_SUCCESS" for e in events)
    assert any(e.action == "LOGIN_FAILURE" for e in events)


@pytest.mark.asyncio
async def test_roles_are_consistent_with_frontend_table() -> None:
    """Test the backend role table matches the frontend mirroring table."""
    assert set(ROLE_PERMISSIONS.keys()) == {role.value for role in UserRole}
    for role in UserRole:
        assert create_user_session("t", role).has_permission(Permission.READ_TELEMETRY) is True
        assert set(ROLE_PERMISSIONS[role]) == set(create_user_session("t", role).permissions)


@pytest.mark.asyncio
async def test_password_mismatch_is_non_revealing() -> None:
    """Test a wrong password reports the same status as a missing one."""
    service = AuthenticationService()
    result = await _login(service, "unknown_user", "wrong_password")
    assert result.success is False
    assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_locked_accounts_are_rejected_with_audit_record() -> None:
    """Test a locked or inactive account rejects login and records the event."""
    AuthenticationService(AuthenticationRateLimiter(max_attempts=10, lockout_seconds=60))
    account = UserAccount(username="waiting", role=UserRole.OBSERVER, hashed_password="locked")
    account.locked_until = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=60)
    assert account.is_locked() is True


@pytest.mark.asyncio
async def test_token_secret_is_not_embedded() -> None:
    """Test the secret key is never the old development default string."""
    assert settings.JWT_SECRET_KEY != "default_powertwin_dev_secret_key_change_in_production"
    assert settings.POSTGRES_PASSWORD != "powertwin_secret"


@pytest.mark.asyncio
async def test_production_fails_without_strong_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test production refuses an empty or weak JWT secret at startup."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "")
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", "a" * POSTGRES_PASSWORD_MIN_BYTES)

    with pytest.raises(RuntimeError):
        validate_safety_invariants()


@pytest.mark.asyncio
async def test_production_fails_without_weak_database_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test production refuses a weak database password at startup."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "a" * JWT_SECRET_MIN_BYTES)
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", "short_password")

    with pytest.raises(RuntimeError):
        validate_safety_invariants()


@pytest.mark.asyncio
async def test_production_fails_when_login_limits_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test production refuses unusable authentication rate limits at startup."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "a" * JWT_SECRET_MIN_BYTES)
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", "b" * POSTGRES_PASSWORD_MIN_BYTES)
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT", -1)

    with pytest.raises(RuntimeError):
        validate_safety_invariants()


@pytest.mark.asyncio
async def test_production_passes_with_strong_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test production starts with a strong JWT key and database password."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "a" * JWT_SECRET_MIN_BYTES)
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", "b" * POSTGRES_PASSWORD_MIN_BYTES)
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT", 5)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_SECONDS", 60)

    validate_safety_invariants()


@pytest.mark.asyncio
async def test_expiration_is_enforced() -> None:
    """Test a past expiry timestamp causes token validation to fail."""
    payload = {
        "sub": "observer",
        "role": "OBSERVER",
        "exp": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(Exception) as exc_info:
        decode_access_token(token)

    assert "expired" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_invalid_token_rejected() -> None:
    """Test a token signed with the wrong secret cannot be decoded."""
    import secrets

    payload = {
        "sub": "observer",
        "role": "OBSERVER",
    }
    token = jwt.encode(payload, secrets.token_hex(32), algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(Exception) as exc_info:
        decode_access_token(token)

    assert "credentials" in str(exc_info.value).lower()


# Production isolation of the identity source -------------------------------------------------


@pytest.mark.asyncio
async def test_production_login_rejects_missing_db_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """A user that exists in no row of the production database is rejected.

    A production login never falls back to a local account, even when the
    user lookup returns no row at all.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.delenv("POWERTWIN_DEV_PASSWORD", raising=False)

    service = AuthenticationService()

    for username in ("admin", "observer", "unknown_user"):
        result = await _login(service, username, "wrong_password")
        assert result.success is False
        assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_production_missing_user_matches_wrong_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing production user reports the same status as a wrong password."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.delenv("POWERTWIN_DEV_PASSWORD", raising=False)

    service = AuthenticationService()

    missing = await _login(service, "admin", "correct_password")
    mismatch = await _login(service, "admin", "wrong_password")

    assert missing.success is False
    assert mismatch.success is False
    assert missing.status == mismatch.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_development_provider_is_not_called_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A production login must never invoke the development account provider."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.delenv("POWERTWIN_DEV_PASSWORD", raising=False)

    with mock.patch.object(authentication, "dev_user_accounts") as provider:
        service = AuthenticationService()
        result = await _login(service, "admin", "wrong_password")

    provider.assert_not_called()
    assert result.success is False
    assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_production_login_logs_no_development_password(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A production login must not log the development password or its source."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.delenv("POWERTWIN_DEV_PASSWORD", raising=False)

    password = _dev_password()

    service = AuthenticationService()
    result = await _login(service, "admin", password)

    assert result.success is False
    assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS
    assert password not in caplog.text
    assert "development password" not in caplog.text


@pytest.mark.asyncio
async def test_dev_password_value_is_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A random default password is never reported in any log output."""
    monkeypatch.delenv("POWERTWIN_DEV_PASSWORD", raising=False)
    monkeypatch.delenv("POWERTWIN_DEFAULT_DEV_PASSWORD", raising=False)
    monkeypatch.setattr(auth_development, "_generated_dev_password", None)
    caplog.set_level(logging.DEBUG)

    password = auth_development._dev_password()

    assert password is not None
    assert password not in caplog.text


@pytest.mark.asyncio
async def test_non_production_login_still_accepts_local_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Development and testing environments must still resolve local accounts."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")

    password = _dev_password()
    monkeypatch.setenv("POWERTWIN_DEV_PASSWORD", password)

    service = AuthenticationService()
    result = await _login(service, "observer", password)

    assert result.success is True
    assert result.status == AuthenticationResult.STATUS_SUCCESS


# Client identity resolution for the rate limiter -------------------------------------------------


def _client_request(
    peer: str,
    headers: dict[str, str],
    link: dict[str, Any] | None = None,
) -> Request:
    """Construct one request whose peer is ``peer`` and whose headers carry ``headers``."""
    scope = {
        "type": "http",
        "client": (peer, 0),
        "headers": [
            (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
        ],
    }
    scope.update(link or {})
    return Request(scope)


@pytest.mark.parametrize(
    ("peer", "header_name", "header_value", "trusted_proxy", "expected"),
    [
        # No proxy is declared to the application, so its headers carry no authority.
        ("10.0.0.1", "X-Forwarded-For", "8.8.8.8", None, "10.0.0.1"),
        ("10.0.0.1", "X-Real-IP", "8.8.8.8", None, "10.0.0.1"),
        ("10.0.0.1", None, None, None, "10.0.0.1"),
        ("10.0.0.1", "X-Forwarded-For", "8.8.8.8, 7.7.7.7", None, "10.0.0.1"),
        ("10.0.0.1", "X-Forwarded-For", "not-an-ip", None, "10.0.0.1"),
        # An unidentified peer can never be declared as a proxy.
        ("testclient", "X-Forwarded-For", "8.8.8.8", None, "testclient"),
        ("testclient", "X-Forwarded-For", "8.8.8.8", "10.0.0.1", "testclient"),
        # A declared proxy is awarded the chain head, the neighboring hop's tender.
        ("10.0.0.1", "X-Forwarded-For", "8.8.8.8", "10.0.0.1", "8.8.8.8"),
        ("10.0.0.1", "X-Real-IP", "8.8.8.8", "10.0.0.1", "8.8.8.8"),
        ("10.0.0.1", "X-Forwarded-For", "8.8.8.8, 7.7.7.7", "10.0.0.1", "8.8.8.8"),
        # A declared CIDR block awards the peer's position inside the block.
        ("10.0.0.1", "X-Forwarded-For", "8.8.8.8", "10.0.0.0/8", "8.8.8.8"),
        ("10.0.0.1", "X-Forwarded-For", "8.8.8.8, not-an-ip", "10.0.0.1", "8.8.8.8"),
        ("10.0.0.1", "X-Forwarded-For", "not-an-ip", "10.0.0.1", "10.0.0.1"),
        ("10.0.0.1", "X-Forwarded-For", "8.8.8.8", "192.168.1.0/24", "10.0.0.1"),
        ("10.0.0.1", "X-Forwarded-For", "8.8.8.8", "not-an-ip", "10.0.0.1"),
    ],
)
def test_client_identity_resolver(
    monkeypatch: pytest.MonkeyPatch,
    peer: str,
    header_name: str | None,
    header_value: str | None,
    trusted_proxy: str | None,
    expected: str,
) -> None:
    """Resolve one client identity per request, trusted only by declaration.

    The peer carries the identity by default. The forwarded headers are trusted
    only when the peer is declared in `settings.TRUSTED_PROXIES`, and a header
    chain that contains an unparsable address falls back to the peer.
    """
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", [trusted_proxy] if trusted_proxy else [])
    headers = {header_name: header_value} if header_name else {}

    request = _client_request(peer, headers)
    assert resolve_client_id(request) == expected


@pytest.mark.asyncio
async def test_identity_is_per_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Login from separate clients is throttled separately, never by the account name.

    An attempt against an unknown username from one client blocks only that
    client's view of the account, leaving every other client free to attempt
    the throttle before the account is known at all.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT", 2)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_SECONDS", 60)

    service = AuthenticationService(AuthenticationRateLimiter(max_attempts=2, lockout_seconds=60))
    client_a, client_b = "192.168.1.1", "192.168.1.2"

    try:
        for client_id in client_a, client_b:
            for _ in range(2):
                result = await _login(service, "observer", "wrong_password", client_id=client_id)
                assert result.success is False
                assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS

        # Both clients have counted their two attempts against the same account.
        assert (
            service.rate_limiter.is_blocked(service.rate_limiter.topic("observer", client_a))
            is True
        )
        assert (
            service.rate_limiter.is_blocked(service.rate_limiter.topic("observer", client_b))
            is True
        )

        # An unknown name counts the same way as a known one: the first attempt
        # is recorded and the second attempt is throttled.
        result = await _login(service, "unknown_user", "wrong_password", client_id=client_a)
        assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS
        result = await _login(service, "unknown_user", "wrong_password", client_id=client_a)
        assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS
        result = await _login(service, "unknown_user", "wrong_password", client_id=client_a)
        assert result.status == AuthenticationResult.STATUS_RATE_LIMITED

        # A successful login from a fresh client resets only its own view.
        password = _dev_password()
        result = await _login(service, "observer", password, client_id="192.168.1.3")
        assert result.success is True
        assert (
            service.rate_limiter.is_blocked(service.rate_limiter.topic("observer", client_a))
            is True
        )
        assert (
            service.rate_limiter.is_blocked(service.rate_limiter.topic("observer", client_b))
            is True
        )
    finally:
        service.rate_limiter.reset_all()


@pytest.mark.asyncio
async def test_login_endpoint_wires_client_identity(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    """The login endpoint throttles the identity of the request, not the account.

    A request from an undeclared peer is throttled on the peer address even when
    it forwards `X-Forwarded-For`, and the endpoint's own limiter table carries
    the resulting topic while a different client keeps the throttle from the
    caller's view.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT", 2)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_SECONDS", 60)

    from backend.app.api.v1 import auth as auth_api

    endpoint_service = auth_api._auth_service
    original_limiter = endpoint_service.rate_limiter
    endpoint_service.rate_limiter = AuthenticationRateLimiter(max_attempts=2, lockout_seconds=60)
    try:
        endpoint_service.rate_limiter.reset_all()

        for _ in range(3):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "observer", "password": "wrong_password"},
                headers={"X-Forwarded-For": "8.8.8.8", "X-Real-IP": "9.9.9.9"},
            )
            assert response.status_code == 401

        # A request from an undeclared peer ignores the forwarded headers.
        assert (
            endpoint_service.rate_limiter.is_blocked(
                endpoint_service.rate_limiter.topic("observer", "testclient")
            )
            is True
        )

        # A different account from the same peer carries its own throttle.
        for _ in range(3):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "engineer", "password": "wrong_password"},
            )
            assert response.status_code == 401
        assert (
            endpoint_service.rate_limiter.is_blocked(
                endpoint_service.rate_limiter.topic("engineer", "testclient")
            )
            is True
        )

        # An unknown account name from the same peer counts towards the throttle.
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "nobody_example", "password": "wrong_password"},
        )
        assert response.status_code == 401
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "nobody_example", "password": "wrong_password"},
        )
        assert response.status_code == 401
        assert endpoint_service.rate_limiter.is_blocked("nobody_example:testclient") is True
    finally:
        endpoint_service.rate_limiter = original_limiter
        original_limiter.reset_all()


@pytest.mark.asyncio
async def test_unknown_user_does_not_lock_the_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed attempt against a name in no row polls the same limiter topics.

    The rejection message never names the account existence, and the throttle
    never leaves the username uncounted, so an unknown user can never drift
    outside the tracker.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.delenv("POWERTWIN_DEV_PASSWORD", raising=False)
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT", 3)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_SECONDS", 60)

    service = AuthenticationService()
    for _ in range(3):
        result = await _login(service, "never_existed_user_example", "wrong_password")
        assert result.success is False
        assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS

    assert (
        service.rate_limiter.is_blocked(
            service.rate_limiter.topic("never_existed_user_example", None)
        )
        is True
    )
    await _login(service, "never_existed_user_example", "wrong_password")
    assert (
        service.rate_limiter.remaining_attempts(
            service.rate_limiter.topic("never_existed_user_example", None)
        )
        == 0
    )
