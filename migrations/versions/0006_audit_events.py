"""audit_events: who queried whose memory (C7)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = (
    "current_setting('neuralgram.context', true) = 'system' "
    "OR (tenant_id IS NOT NULL AND tenant_id = current_setting('neuralgram.tenant_id', true))"
)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("resource", sa.String(512), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON audit_events USING ({POLICY})")


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON audit_events")
    op.drop_table("audit_events")
