"""C2.3 deep scoring, entity extraction and embedding — the extract_chunk job.

The model is asked (hint:fast) for a JSON verdict; when the response is
not parseable JSON (always true for the deterministic mock provider) a
heuristic fallback scores and extracts deterministically (ADR-0008), so
lifecycle behavior is identical and testable in CI.
"""

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.compression.engine import compress
from neuralgram.memory.embeddings import persist_embeddings
from neuralgram.memory.queue import JobQueue
from neuralgram.observability.logging import get_logger
from neuralgram.router.gateway import Message, ModelGateway
from neuralgram.storage.models import Chunk, ChunkEntity, Entity, Score

ADMIT_THRESHOLD = 0.3
EXTRACTION_BUDGET_TOKENS = 2000

logger = get_logger(__name__)

_ENTITY_PATTERN = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?: [A-Z][a-zA-Z0-9]+)*)\b")
_STOPWORDS = {"The", "This", "That", "There", "Please", "It", "We", "You", "Friday", "Monday"}

_EXTRACTION_PROMPT = (
    "Score the following content for long-term memory value (0..1) and list named "
    'entities. Reply with JSON: {"score": float, "entities": [{"name": str, "type": str}]}.'
    "\n\n---\n"
)


class ExtractionVerdict(BaseModel):
    """Score + entities for one chunk, from the model or the fallback."""

    score: float = Field(ge=0.0, le=1.0)
    entities: list[dict[str, str]] = []


def heuristic_verdict(content: str) -> ExtractionVerdict:
    """Deterministic fallback: lexical-richness score + capitalized-phrase entities."""
    words = content.split()
    unique_ratio = len(set(words)) / len(words) if words else 0.0
    length_factor = min(len(words) / 40.0, 1.0)
    score = round(min(unique_ratio * 0.5 + length_factor * 0.5, 1.0), 4)

    names = [
        m.group(1)
        for m in _ENTITY_PATTERN.finditer(content)
        if m.group(1) not in _STOPWORDS and len(m.group(1)) > 2
    ]
    seen: set[str] = set()
    entities = []
    for name in names:
        if name.lower() not in seen:
            seen.add(name.lower())
            entities.append({"name": name, "type": "unknown"})
    return ExtractionVerdict(score=score, entities=entities[:16])


def parse_model_verdict(text: str) -> ExtractionVerdict | None:
    """Parse a model reply into a verdict; None when the reply is not valid JSON."""
    try:
        raw = json.loads(text)
        return ExtractionVerdict.model_validate(raw)
    except (json.JSONDecodeError, ValueError):
        return None


class Extractor:
    """Runs the extract_chunk job: score, entities, embedding, lifecycle."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: ModelGateway,
        admit_threshold: float = ADMIT_THRESHOLD,
        queue: JobQueue | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._gateway = gateway
        self._admit_threshold = admit_threshold
        self._queue = queue

    async def extract_chunk(self, payload: dict[str, Any]) -> None:
        """Handler for `extract_chunk` jobs; payload = {"chunk_id": ...}."""
        chunk_id = payload["chunk_id"]
        async with self._session_factory() as session:
            chunk = await session.get(Chunk, chunk_id)
            if chunk is None or chunk.lifecycle != "pending_extraction":
                logger.info("extract.skipped", chunk_id=chunk_id)
                return

            compressed = compress(chunk.content_md, EXTRACTION_BUDGET_TOKENS)
            reply = await self._gateway.complete(
                [Message(role="user", content=_EXTRACTION_PROMPT + compressed.text)],
                "hint:fast",
                tenant_id=chunk.tenant_id,
            )
            verdict = parse_model_verdict(reply.text) or heuristic_verdict(chunk.content_md)
            embedding = (await self._gateway.embed([compressed.text], tenant_id=chunk.tenant_id))[0]

            lifecycle = "admitted" if verdict.score >= self._admit_threshold else "dropped"
            linked_entity_ids: list[str] = []
            await persist_embeddings(session, {chunk_id: embedding})
            await session.execute(
                update(Score).where(Score.chunk_id == chunk_id).values(deep_score=verdict.score)
            )
            if lifecycle == "admitted":
                linked_entity_ids = await self._link_entities(session, chunk, verdict)
            await session.execute(
                update(Chunk).where(Chunk.id == chunk_id).values(lifecycle=lifecycle)
            )
            await session.commit()
            logger.info("extract.done", chunk_id=chunk_id, lifecycle=lifecycle, score=verdict.score)
        if lifecycle == "admitted" and self._queue is not None:
            await self._queue.enqueue("append_buffer", {"chunk_id": chunk_id}, f"buffer:{chunk_id}")
            for entity_id in linked_entity_ids:
                await self._queue.enqueue(
                    "topic_route", {"entity_id": entity_id}, f"topic:{entity_id}:{chunk_id}"
                )

    async def _link_entities(
        self, session: AsyncSession, chunk: Chunk, verdict: ExtractionVerdict
    ) -> list[str]:
        linked: list[str] = []
        for item in verdict.entities:
            name, kind = item["name"], item.get("type", "unknown")
            entity_id = hashlib.sha256(
                f"{chunk.tenant_id}\n{name.lower()}\n{kind}".encode()
            ).hexdigest()
            entity_row = (
                insert(Entity)
                .values(
                    id=entity_id,
                    tenant_id=chunk.tenant_id,
                    name=name,
                    type=kind,
                    last_seen=chunk.created_at,
                )
                .on_conflict_do_update(
                    index_elements=[Entity.id], set_={"last_seen": chunk.created_at}
                )
            )
            await session.execute(entity_row)
            link = (
                insert(ChunkEntity)
                .values(chunk_id=chunk.id, entity_id=entity_id)
                .on_conflict_do_nothing()
            )
            await session.execute(link)
            linked.append(entity_id)
        return linked
