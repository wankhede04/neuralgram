"""Unit tests on storage model metadata (M1-1)."""

from sqlalchemy import UniqueConstraint

from neuralgram.storage.models import Base, Chunk, Job


def test_chunks_content_hash_has_unique_constraint() -> None:
    constraints = [c for c in Chunk.__table__.constraints if isinstance(c, UniqueConstraint)]
    assert any(
        [col.name for col in constraint.columns] == ["content_hash"] for constraint in constraints
    )


def test_jobs_dedupe_key_has_unique_constraint() -> None:
    constraints = [c for c in Job.__table__.constraints if isinstance(c, UniqueConstraint)]
    assert any(
        [col.name for col in constraint.columns] == ["dedupe_key"] for constraint in constraints
    )


def test_tenant_scoped_tables_carry_tenant_id() -> None:
    for table_name in ("chunks", "entities", "summaries"):
        table = Base.metadata.tables[table_name]
        assert "tenant_id" in table.columns, f"{table_name} must carry tenant_id"
