"""R-3 rollback drill: one-step migration rollback with live data, rehearsed.

Simulates the production rollback procedure (ops/runbooks/deploy-rollback.md):
data exists at head -> `alembic downgrade -1` -> app data survives ->
`alembic upgrade head` -> schema fully restored.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from neuralgram.storage.models import AuditEvent, Chunk

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def async_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        assert _alembic(url, "upgrade", "head").returncode == 0
        yield url


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=os.environ | {"DATABASE_URL": url},
        capture_output=True,
        text=True,
    )


async def test_one_step_rollback_with_data_then_roll_forward(async_url: str) -> None:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chunk_id = uuid.uuid4().hex
    async with factory() as session:
        session.add(
            Chunk(
                id=chunk_id,
                tenant_id="tenant-rollback",
                source_id="C042MEMORY",
                content_md="survives the rollback",
                token_count=3,
                provenance={"source_type": "slack"},
                lifecycle="admitted",
                content_hash=chunk_id,
            )
        )
        session.add(
            AuditEvent(
                id=uuid.uuid4().hex,
                tenant_id="tenant-rollback",
                actor="drill",
                action="GET",
                resource="/memory/search",
                status=200,
            )
        )
        await session.commit()

    # Rollback one migration (0006 -> 0005): audit_events is sacrificed by design.
    down = _alembic(async_url, "downgrade", "-1")
    assert down.returncode == 0, down.stderr

    async with engine.connect() as conn:
        survived = await conn.execute(
            text("SELECT count(*) FROM chunks WHERE id = :i"), {"i": chunk_id}
        )
        assert survived.scalar_one() == 1, "app data must survive a one-step rollback"
        tables = {
            row[0]
            for row in await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        assert "audit_events" not in tables

    # Roll forward again: schema fully restored.
    up = _alembic(async_url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    async with engine.connect() as conn:
        tables = {
            row[0]
            for row in await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        assert "audit_events" in tables
    await engine.dispose()
