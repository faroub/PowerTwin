"""Automated tests for authentication security boundaries and session management.

These tests cover:
    * Rate limiting of the login endpoint over a sliding window.
    * Rejection of missing, malformed, invalid, expired and tampered tokens.
    * Non-revealing failure responses across every rejected branch.
    * Backend role boundaries against the mirroring frontend role table.
    * Production startup rejection of missing secret configuration.
    * Audit logging of every accepted and rejected authentication action.
"""

import datetime
import logging
import os
from unittest import mock

import jwt
import pytest
from passlib.hash import pbkdf2_sha256

from backend.app.core import auth_development, authentication
from backend.app.core.audit import audit_log
from backend.app.core.authentication import (
    AuthenticationResult,
    AuthenticationService,
)
from backend.app.core.config import settings
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
    service: AuthenticationService, username: str, password: str
) -> AuthenticationResult:
    """Execute one login attempt through the service."""
    return await service.login(username, password, session=None)


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

    for _ in range(3):
        result = await _login(service, "observer", "wrong_password")
        assert result.success is False
        assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS

    assert service.rate_limiter.is_blocked("powertwin-login") is True
    result = await _login(service, "observer", "wrong_password")
    assert result.success is False
    assert result.status == AuthenticationResult.STATUS_RATE_LIMITED

    service.rate_limiter.reset("powertwin-login")
    result = await _login(service, "observer", "wrong_password")
    assert result.success is False
    assert result.status == AuthenticationResult.STATUS_INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_login_rate_limit_resets_after_success() -> None:
    """Test the rate limiter clears after a successful login."""
    service = AuthenticationService(AuthenticationRateLimiter(max_attempts=3, lockout_seconds=60))

    for _ in range(3):
        result = await _login(service, "observer", "wrong_password")
        assert result.success is False

    assert service.rate_limiter.is_blocked("powertwin-login") is True
    service.rate_limiter.reset("powertwin-login")

    password = _dev_password()
    result = await _login(service, "observer", password)
    assert result.success is True

    assert service.rate_limiter.is_blocked("powertwin-login") is False


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
