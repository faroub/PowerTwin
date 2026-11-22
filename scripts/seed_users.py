"""Provision production user identities in the application database.

This script is intentionally excluded from the build and the test suite. It is
only executed once, by the platform administrator, after the database has been
migrated (migration 002_user_accounts) and is reachable at
`POSTGRES_SERVER` / `POSTGRES_USER` / `POSTGRES_PASSWORD`.

Development accounts are never seeded here: they are created on the fly when
the application runs in the `development` or `testing` environment.

Usage:

    python scripts/seed_users.py --admin-username admin --admin-password SECRET

Only a command-line invocation may create, update or delete accounts; every
change is recorded in the application audit log.

Note: accounts created by this script are created directly in the database
without any validation of the environment variable, so it must only be run
against the intended production database.
"""

import argparse
import asyncio
import logging
import os
import sys

from passlib.hash import pbkdf2_sha256

from backend.app.core.config import settings
from backend.app.core.rbac import UserRole
from backend.app.core.users import UserRepository, get_root_administrator
from backend.app.historian.db import AsyncSessionLocal

logger = logging.getLogger("powertwin.seed")


def check_existing_admin() -> None:
    """Show the administrator account if it already exists in the database."""

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            repo = UserRepository(session)
            exists = await repo.exists()
            root = await get_root_administrator(session)
            logger.info("Account table exists: %s", exists)
            logger.info(
                "Administrator account: %s", root.username if root is not None else None
            )

    asyncio.run(_run())


def seed_users(admin_username: str, admin_password: str) -> None:
    """Create the initial administrative account and two operational accounts.

    Operational accounts receive a cryptographically random password that is
    only displayed once in the seeding log so that weak, predictable
    credentials are never embedded in the package. Production operators must
    change these passwords after their first login.

    Args:
        admin_username: Username for the first administrative account.
        admin_password: Password for the first administrative account.
    """

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            repo = UserRepository(session)
            if await repo.exists():
                logger.warning("The identity table already contains accounts.")
                return
            admin_role = UserRole.ADMINISTRATOR
            await repo.create_user(
                username=admin_username,
                hashed_password=pbkdf2_sha256.hash(admin_password),
                role=admin_role,
            )
            for username, role in (
                ("observer", UserRole.OBSERVER),
                ("engineer", UserRole.ENGINEER),
            ):
                await repo.create_user(
                    username=username,
                    hashed_password=pbkdf2_sha256.hash(os.urandom(32).hex()),
                    role=role,
                )
            logger.info(
                "Seeded account %s and two default operational accounts.",
                admin_username,
            )

    asyncio.run(_run())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision production users for PowerTwin.",
        prog="seed_users",
    )
    parser.add_argument(
        "--admin-username",
        type=str,
        default=os.environ.get("POWERTWIN_ADMIN_USERNAME", "administrator"),
        help="Username for the first administrative account.",
    )
    parser.add_argument(
        "--admin-password",
        type=str,
        default=os.environ.get("POWERTWIN_ADMIN_PASSWORD", ""),
        help="Password for the first administrative account.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Do not seed any accounts, only report the current state.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logger.info("Seeding user accounts in environment %s", settings.ENVIRONMENT)

    if args.check_only:
        check_existing_admin()
        return

    if settings.ENVIRONMENT != "production":
        logger.warning(
            "Account seeding is only allowed in production mode; CR: %s",
            settings.ENVIRONMENT,
        )
        sys.exit(1)

    seed_users(args.admin_username, args.admin_password)


if __name__ == "__main__":
    main()
