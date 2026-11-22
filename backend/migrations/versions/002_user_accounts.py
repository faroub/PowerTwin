"""User accounts and authentication persistence.

This migration introduces the user identity table used by the application
authentication and role-based access control subsystem.

Development starting accounts are seeded by `backend.app.core.rbac` at startup
only when `settings.ENVIRONMENT` is `development`. No production identities are
hard coded here.

Revision ID: 002_user_accounts
Revises: 001_initial_schema
Create Date: 2025-01-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_user_accounts"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, default=0),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    # Username revoked when the application is reset
    op.create_index("idx_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_table("users")
