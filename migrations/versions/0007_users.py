"""users: self-serve signup identity, one user = one tenant = one key (M5-2 ext)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("hashed_key", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="writer"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_hashed_key", "users", ["hashed_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_hashed_key", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
