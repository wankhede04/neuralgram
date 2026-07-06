"""Integration: Postgres RLS tenant isolation (M5-1 acceptance).

Connects as a NON-superuser role (superusers bypass RLS — the prod app
role must never be superuser, see ADR-0014) and proves:
  - no tenant context  -> zero rows (fail-closed)
  - tenant A's context -> only A's rows, even via raw SQL
  - system context     -> all rows (trusted worker paths)
"""

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from neuralgram.common.db import build_system_session_factory, tenant_session
from neuralgram.storage.models import Chunk

REPO_ROOT = Path(__file__).resolve().parents[2]

APP_ROLE = "neuralgram_app"
APP_PASSWORD = "app-role-test-password"  # pragma: allowlist secret


@pytest.fixture(scope="module")
def urls() -> Iterator[tuple[str, str]]:
    """(superuser_url, app_role_url) against a migrated database."""
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        super_url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=os.environ | {"DATABASE_URL": super_url},
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stderr

        import asyncio

        async def _create_role() -> None:
            engine = create_async_engine(super_url, isolation_level="AUTOCOMMIT")
            async with engine.connect() as conn:
                await conn.execute(
                    text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' NOSUPERUSER")
                )
                grant = (
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                    f"IN SCHEMA public TO {APP_ROLE}"
                )
                await conn.execute(text(grant))
            await engine.dispose()

        asyncio.run(_create_role())
        host_part = super_url.split("@", 1)[1]
        app_url = f"postgresql+asyncpg://{APP_ROLE}:{APP_PASSWORD}@{host_part}"
        yield super_url, app_url


def _chunk_row(tenant: str) -> Chunk:
    chunk_id = uuid.uuid4().hex
    return Chunk(
        id=chunk_id,
        tenant_id=tenant,
        source_id="C042MEMORY",
        content_md=f"secret notes for {tenant}",
        token_count=4,
        provenance={"source_type": "slack"},
        lifecycle="admitted",
        content_hash=chunk_id,
    )


@pytest.fixture(scope="module")
def seeded(urls: tuple[str, str]) -> None:
    import asyncio

    async def _seed() -> None:
        engine = create_async_engine(urls[0])  # superuser bypasses RLS for seeding
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add_all(
                [_chunk_row("tenant-a"), _chunk_row("tenant-a"), _chunk_row("tenant-b")]
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_seed())


@pytest.fixture
async def app_engine(urls: tuple[str, str]) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(urls[1])
    try:
        yield engine
    finally:
        await engine.dispose()


async def _tenants_visible(session: AsyncSession) -> set[str]:
    rows = await session.execute(text("SELECT DISTINCT tenant_id FROM chunks"))
    return {row[0] for row in rows}


async def test_no_context_sees_nothing(seeded: None, app_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(app_engine, expire_on_commit=False)
    async with factory() as session:
        assert await _tenants_visible(session) == set(), "RLS must fail closed"


async def test_tenant_a_cannot_read_tenant_b_even_via_raw_sql(
    seeded: None, app_engine: AsyncEngine
) -> None:
    factory = async_sessionmaker(app_engine, expire_on_commit=False)
    async with tenant_session(factory, "tenant-a") as session:
        assert await _tenants_visible(session) == {"tenant-a"}
        stolen = await session.execute(
            text("SELECT content_md FROM chunks WHERE tenant_id = 'tenant-b'")
        )
        assert stolen.all() == [], "raw SQL for another tenant must return nothing"


async def test_system_context_sees_all_tenants(seeded: None, app_engine: AsyncEngine) -> None:
    factory = build_system_session_factory(app_engine)
    async with factory() as session:
        assert await _tenants_visible(session) >= {"tenant-a", "tenant-b"}


async def test_rls_applies_to_scores_and_summaries_tables(
    seeded: None, app_engine: AsyncEngine
) -> None:
    factory = async_sessionmaker(app_engine, expire_on_commit=False)
    async with factory() as session:
        for table in ("scores", "entities", "chunk_entities", "summaries", "usage_events"):
            rows = await session.execute(text(f"SELECT count(*) FROM {table}"))
            assert rows.scalar_one() == 0, f"{table} must be fail-closed without context"
