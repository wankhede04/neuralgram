"""storage models: chunks, scores, entities, chunk_entities, summaries, jobs

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("source_id", sa.String(255), nullable=False, index=True),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("provenance", JSONB(), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False, index=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("content_hash", name="uq_chunks_content_hash"),
    )
    op.create_table(
        "scores",
        sa.Column(
            "chunk_id",
            sa.String(64),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fast_score", sa.Float(), nullable=True),
        sa.Column("deep_score", sa.Float(), nullable=True),
        sa.Column("hotness", sa.Float(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )
    op.create_table(
        "entities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("hotness", sa.Float(), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "chunk_entities",
        sa.Column(
            "chunk_id",
            sa.String(64),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "entity_id",
            sa.String(64),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "summaries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("tree_type", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.String(255), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("child_ids", JSONB(), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False, index=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),
    )


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("summaries")
    op.drop_table("chunk_entities")
    op.drop_table("entities")
    op.drop_table("scores")
    op.drop_table("chunks")
