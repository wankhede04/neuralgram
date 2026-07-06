"""Integration: Alembic migrations run up and down cleanly on real Postgres (P0-5 acceptance)."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def async_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        yield container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )


def _alembic(async_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"DATABASE_URL": async_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


async def _extension_installed(async_url: str) -> bool:
    engine = create_async_engine(async_url)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                )
            ).first()
        return row is not None
    finally:
        await engine.dispose()


async def test_migrations_up_and_down_are_clean(async_url: str) -> None:
    up = _alembic(async_url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert await _extension_installed(async_url)

    down = _alembic(async_url, "downgrade", "base")
    assert down.returncode == 0, down.stderr
    assert not await _extension_installed(async_url)

    again = _alembic(async_url, "upgrade", "head")
    assert again.returncode == 0, again.stderr
    assert await _extension_installed(async_url)
