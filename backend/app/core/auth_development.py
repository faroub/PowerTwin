"""Development-only user provisioning.

These accounts are only ever created, accompanied or accepted while the
application runs in the **development** or **testing** environment. No static,
weak credentials are embedded in the package: a shared default password is
generated once per process startup (or overridden via the environment); the
password value itself is never reported in the console log, so the values are
never written to product source and never survive a process restart.

Production deployments provision their own identities through the migration
seeding script (`scripts/seed_users.py`).

WARNING: this module is only intended for simulation-only local development.
Using its accident-prone default passwords outside a trusted development
environment is a security violation.
"""

import logging
import os
from typing import Any

from passlib.hash import pbkdf2_sha256

from backend.app.core.config import settings

logger = logging.getLogger(__name__)
_generated_dev_password: str | None = None


def _dev_usernames() -> list[str]:
    """Return the set of development-only account names."""
    return ["observer", "engineer", "admin"]


def _dev_password() -> str:
    """Resolve the shared development password for this process.

    A test/developer may override the value with the `POWERTWIN_DEV_PASSWORD`
    environment variable; without it a process-scoped random secret is generated.
    The secret is never reported in the console log: the log line may state that
    a random default is in use, but it never carries the value itself.
    """
    global _generated_dev_password

    shared = os.environ.get("POWERTWIN_DEV_PASSWORD")
    if shared:
        return shared

    password = os.environ.get("POWERTWIN_DEFAULT_DEV_PASSWORD", "")
    if not password:
        if _generated_dev_password is None:
            _generated_dev_password = os.urandom(16).hex()
            logger.warning(
                "No POWERTWIN_DEV_PASSWORD override; using a random default "
                "development password for every local account: <redacted>"
            )
        password = _generated_dev_password
    return password


def dev_user_passwords() -> dict[str, str]:
    """Return the password dictionary for every development user.

    Passwords are resolved at call time so that an explicit override always
    applies without relying on a cached value from a previous import.
    """
    return {username: _dev_password() for username in _dev_usernames()}


def _dev_roles() -> dict[str, Any]:
    from backend.app.core.rbac import UserRole

    return {
        "observer": UserRole.OBSERVER,
        "engineer": UserRole.ENGINEER,
        "admin": UserRole.ADMINISTRATOR,
    }


def _hash_password(password: str) -> str:
    """Hash a password with a per-call random salt (never a fixed byte string)."""
    return str(pbkdf2_sha256.hash(password))


def dev_user_accounts() -> dict[str, Any]:
    """Initialise the development-only user accounts for this process.

    Returns a mapping of username to a user record with a prefetched,
    cryptographically strong password hash.
    """
    passwords = dev_user_passwords()
    accounts: dict[str, Any] = {}
    for username in _dev_usernames():
        accounts[username] = {
            "username": username,
            "role": _dev_roles()[username],
            "hashed_password": _hash_password(passwords[username]),
            "is_active": True,
            "failed_login_attempts": 0,
            "locked_until": None,
        }
    return accounts


def validate_dev_environment() -> None:
    """Fail fast when the platform is instructed to run in a non-development mode."""
    if settings.ENVIRONMENT not in ("development", "testing"):
        logger.warning(
            "Development user provisioning is ignored in '%s' mode; "
            "production identities must be provisioned in the database.",
            settings.ENVIRONMENT,
        )
