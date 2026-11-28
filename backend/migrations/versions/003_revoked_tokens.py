"""Records of revoked session tokens.

This migration adds the table the token revocation subsystem uses to refuse a
token that the platform terminated: a logout, a user deactivation or an
administrative revocation.

A row carries the token's ``jti`` (JWT ID) claim, the account that holds it and
the token's expiry, so revoked rows stop accumulating once a token expires by
itself.

Revision ID: 003_revoked_tokens
Revises: 002_user_accounts
Create Date: 2025-01-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_revoked_tokens"
down_revision: str | None = "002_user_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(36), nullable=False),
        sa.Column("sub", sa.String(64), nullable=False),
        sa.Column(
            "revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False, server_default="LOGOUT"),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index("idx_revoked_tokens_sub", "revoked_tokens", ["sub"])


def downgrade() -> None:
    op.drop_index("idx_revoked_tokens_sub", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
