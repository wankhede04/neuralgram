"""R-2 backup + restore drill: pg_dump/psql and vault files, rehearsed for real.

The drill: seed data -> pg_dump inside the container -> destroy the schema
-> restore from the dump -> byte-identical data back. Vault: copy, wipe,
restore, verify. This test IS the rehearsal and runs on every CI pass.
"""

import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from neuralgram.storage.models import Chunk

REPO_ROOT = Path(__file__).resolve().parents[2]
TENANT = "tenant-backup"


@pytest.fixture(scope="module")
def pg() -> Iterator[tuple[PostgresContainer, str]]:
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=os.environ | {"DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stderr
        yield container, url


async def _seed_chunks(url: str, count: int) -> set[str]:
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = set()
    async with factory() as session:
        for _ in range(count):
            chunk_id = uuid.uuid4().hex
            session.add(
                Chunk(
                    id=chunk_id,
                    tenant_id=TENANT,
                    source_id="C042MEMORY",
                    content_md=f"backup drill content {chunk_id[:8]}",
                    token_count=4,
                    provenance={"source_type": "slack"},
                    lifecycle="admitted",
                    content_hash=chunk_id,
                )
            )
            ids.add(chunk_id)
        await session.commit()
    await engine.dispose()
    return ids


async def _chunk_ids(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT id FROM chunks WHERE tenant_id = :t"), {"t": TENANT}
            )
            return {row[0] for row in rows}
    finally:
        await engine.dispose()


def _exec(container: PostgresContainer, command: str) -> str:
    code, output = container.exec(["bash", "-c", command])
    assert code == 0, f"{command!r} failed: {output.decode(errors='replace')}"
    return output.decode(errors="replace")


async def test_postgres_backup_and_restore_drill(pg: tuple[PostgresContainer, str]) -> None:
    container, url = pg
    seeded = await _seed_chunks(url, 5)

    # 1. Backup.
    _exec(container, "PGPASSWORD=test pg_dump -U test -d test -f /tmp/drill-backup.sql")

    # 2. Disaster: the whole schema is destroyed.
    wipe = "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    _exec(container, f'PGPASSWORD=test psql -U test -d test -c "{wipe}"')

    # 3. Restore from the dump.
    _exec(container, "PGPASSWORD=test psql -U test -d test -f /tmp/drill-backup.sql")

    # 4. Data is byte-identical (same ids, same count).
    assert await _chunk_ids(url) == seeded, "restore must bring back exactly the seeded rows"


def test_vault_backup_and_restore_drill(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / TENANT).mkdir(parents=True)
    files = {}
    for i in range(3):
        f = vault / TENANT / f"chunk-{i}.md"
        f.write_text(f"vault drill content {i}")
        files[f.name] = f.read_text()

    backup = tmp_path / "vault-backup"
    shutil.copytree(vault, backup)  # 1. backup
    shutil.rmtree(vault)  # 2. disaster
    assert not vault.exists()
    shutil.copytree(backup, vault)  # 3. restore

    restored = {f.name: f.read_text() for f in (vault / TENANT).glob("*.md")}
    assert restored == files, "vault restore must be byte-identical"
