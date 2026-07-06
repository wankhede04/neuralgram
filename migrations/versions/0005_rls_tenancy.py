"""org tenancy: tenant_id on scores/chunk_entities + fail-closed RLS

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = ("chunks", "scores", "entities", "chunk_entities", "summaries", "usage_events")

# Fail-closed: no GUC set -> no rows. Workers set context='system'; API
# sessions set tenant_id from the authenticated tenant.
POLICY = (
    "current_setting('neuralgram.context', true) = 'system' "
    "OR (tenant_id IS NOT NULL AND tenant_id = current_setting('neuralgram.tenant_id', true))"
)


def upgrade() -> None:
    op.add_column("scores", sa.Column("tenant_id", sa.String(64), nullable=True))
    op.execute(
        "UPDATE scores SET tenant_id = chunks.tenant_id "
        "FROM chunks WHERE scores.chunk_id = chunks.id"
    )
    op.alter_column("scores", "tenant_id", nullable=False)
    op.create_index("ix_scores_tenant_id", "scores", ["tenant_id"])

    op.add_column("chunk_entities", sa.Column("tenant_id", sa.String(64), nullable=True))
    op.execute(
        "UPDATE chunk_entities SET tenant_id = chunks.tenant_id "
        "FROM chunks WHERE chunk_entities.chunk_id = chunks.id"
    )
    op.alter_column("chunk_entities", "tenant_id", nullable=False)
    op.create_index("ix_chunk_entities_tenant_id", "chunk_entities", ["tenant_id"])

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({POLICY})")


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_chunk_entities_tenant_id", table_name="chunk_entities")
    op.drop_column("chunk_entities", "tenant_id")
    op.drop_index("ix_scores_tenant_id", table_name="scores")
    op.drop_column("scores", "tenant_id")
