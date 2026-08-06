"""users: unique tenant_id, role check constraint (final review fixes)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-06

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0007 created a non-unique ix_users_tenant_id via the column's index=True;
    # this additive unique index is what actually prevents tenant collisions.
    op.create_index("ix_users_tenant_id_unique", "users", ["tenant_id"], unique=True)
    op.create_check_constraint(
        "ck_users_role", "users", "role IN ('reader', 'writer', 'admin')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_index("ix_users_tenant_id_unique", table_name="users")
