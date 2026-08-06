"""SQLAlchemy models for the storage layer (C6, spec §2 schema sketch).

`chunks` is the M1 workhorse; `scores`, `entities`, `chunk_entities`,
`summaries` and `jobs` are created now as stubs and grow in M2/M3.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    """Shared metadata root; Alembic autogenerate diffs against this."""

    type_annotation_map: ClassVar[dict[type, object]] = {
        dict[str, Any]: JSON().with_variant(JSONB(), "postgresql")
    }


class Chunk(Base):
    """A content-addressed, ≤3k-token unit of canonical Markdown (C2.1)."""

    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_chunks_content_hash"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(255), index=True)
    content_md: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    provenance: Mapped[dict[str, Any]] = mapped_column()
    lifecycle: Mapped[str] = mapped_column(String(32), default="pending_extraction", index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Score(Base):
    """Scoring + embedding enrichment for a chunk (C2.3; populated in M2)."""

    __tablename__ = "scores"

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    fast_score: Mapped[float | None] = mapped_column(Float)
    deep_score: Mapped[float | None] = mapped_column(Float)
    hotness: Mapped[float | None] = mapped_column(Float)
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))


class Entity(Base):
    """A named entity extracted from chunks (C2.3; populated in M2)."""

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    type: Mapped[str] = mapped_column(String(64))
    hotness: Mapped[float | None] = mapped_column(Float)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChunkEntity(Base):
    """Many-to-many link between chunks and entities."""

    __tablename__ = "chunk_entities"

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)


class Summary(Base):
    """A node in a source/topic/global summary tree (C2.4; populated in M3)."""

    __tablename__ = "summaries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    tree_type: Mapped[str] = mapped_column(String(32))
    scope_id: Mapped[str] = mapped_column(String(255))
    level: Mapped[int] = mapped_column(Integer)
    body_md: Mapped[str] = mapped_column(Text)
    child_ids: Mapped[dict[str, Any]] = mapped_column()
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    """One metered model call: tokens and cost attributed to a tenant (C4/C8)."""

    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    hint: Mapped[str | None] = mapped_column(String(32))
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    """One audited memory-API access: who touched whose memory (C7, M5-2)."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))
    resource: Mapped[str] = mapped_column(String(512))
    status: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class User(Base):
    """Self-serve signup identity: one user = one tenant = one active API key.

    No RLS here — this is a system identity table (like `jobs`), not
    tenant-scoped data. Only ever queried via the system session factory,
    before a tenant context can even be established (M5-2 extension).
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    hashed_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="writer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    """A durable queue job (C2.2; queue semantics land in M2-1)."""

    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column()
    dedupe_key: Mapped[str] = mapped_column(String(255))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
