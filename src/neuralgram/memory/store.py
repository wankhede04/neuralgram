"""C2.1 content store: hot-path persistence of chunks to Postgres + the .md vault.

The hot path is synchronous and LLM-free: one DB transaction inserts chunk
rows (idempotent via ON CONFLICT DO NOTHING on the content hash) and writes
one vault file per *newly inserted* chunk. On any failure the transaction
rolls back and files created in this call are removed — no dangling rows.
"""

from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.memory.chunker import ChunkDraft
from neuralgram.storage.models import Chunk


class PersistResult(BaseModel):
    """Outcome of a persist call: how many chunks were new vs already stored."""

    inserted: int
    skipped: int
    inserted_ids: list[str] = []


class ContentStore:
    """Writes chunks to the database and the Markdown vault in one transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], vault_root: Path) -> None:
        self._session_factory = session_factory
        self._vault_root = vault_root

    def vault_file(self, tenant_id: str, chunk_id: str) -> Path:
        """Return the vault path for a chunk's Markdown file."""
        return self._vault_root / tenant_id / f"{chunk_id}.md"

    def _write_vault_file(self, draft: ChunkDraft) -> Path:
        path = self.vault_file(draft.tenant_id, draft.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft.content_md, encoding="utf-8")
        return path

    async def persist(self, drafts: list[ChunkDraft]) -> PersistResult:
        """Persist `drafts` atomically; duplicates (same content hash) are skipped.

        Returns counts of inserted vs skipped chunks. Raises on failure with
        the transaction rolled back and this call's vault files removed.
        """
        drafts = list({draft.id: draft for draft in drafts}.values())
        if not drafts:
            return PersistResult(inserted=0, skipped=0)

        written: list[Path] = []
        try:
            async with self._session_factory() as session:
                inserted_ids = await self._insert_rows(session, drafts)
                for draft in drafts:
                    if draft.id in inserted_ids:
                        written.append(self._write_vault_file(draft))
                await session.commit()
        except BaseException:
            for path in written:
                path.unlink(missing_ok=True)
            raise

        return PersistResult(
            inserted=len(inserted_ids),
            skipped=len(drafts) - len(inserted_ids),
            inserted_ids=sorted(inserted_ids),
        )

    async def _insert_rows(self, session: AsyncSession, drafts: list[ChunkDraft]) -> set[str]:
        statement = (
            insert(Chunk)
            .values(
                [
                    {
                        "id": draft.id,
                        "tenant_id": draft.tenant_id,
                        "source_id": draft.source_id,
                        "content_md": draft.content_md,
                        "token_count": draft.token_count,
                        "provenance": draft.provenance.model_dump(mode="json"),
                        "lifecycle": draft.lifecycle,
                        "content_hash": draft.content_hash,
                    }
                    for draft in drafts
                ]
            )
            .on_conflict_do_nothing(constraint="uq_chunks_content_hash")
            .returning(Chunk.id)
        )
        result = await session.execute(statement)
        return {row[0] for row in result}
