"""C2.1 chunker: split canonical docs into bounded, content-addressed units.

Chunk IDs are `sha256(tenant_id + normalized content)` (ADR-0005), so the
same input always produces the same IDs — re-ingest is idempotent and the
DB unique constraint on `content_hash` rejects duplicates — while identical
content in different tenants never collides.
"""

import hashlib
import math

from pydantic import BaseModel

from neuralgram.ingestion.canonicalize import CanonicalDoc, Provenance

DEFAULT_MAX_TOKENS = 3000
_CHARS_PER_TOKEN = 4


class ChunkDraft(BaseModel):
    """An unpersisted chunk: everything the store needs to write a row (M1-4)."""

    id: str
    tenant_id: str
    source_id: str
    content_md: str
    token_count: int
    provenance: Provenance
    content_hash: str
    lifecycle: str = "pending_extraction"


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate (~4 chars/token heuristic), never zero for non-empty text."""
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def _normalize(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def _hard_split(text: str, budget_chars: int) -> list[str]:
    """Split an oversized block, preferring whitespace boundaries near the budget."""
    pieces: list[str] = []
    remaining = text
    while len(remaining) > budget_chars:
        window = remaining[:budget_chars]
        cut = window.rfind(" ")
        if cut < budget_chars // 2:
            cut = budget_chars
        pieces.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _split_blocks(text: str, max_tokens: int) -> list[str]:
    budget_chars = max_tokens * _CHARS_PER_TOKEN
    blocks: list[str] = []
    for paragraph in text.split("\n\n"):
        if not paragraph.strip():
            continue
        if len(paragraph) <= budget_chars:
            blocks.append(paragraph)
        else:
            blocks.extend(_hard_split(paragraph, budget_chars))

    merged: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= budget_chars:
            current = candidate
        else:
            merged.append(current)
            current = block
    if current:
        merged.append(current)
    return merged


def chunk(
    doc: CanonicalDoc, tenant_id: str, max_tokens: int = DEFAULT_MAX_TOKENS
) -> list[ChunkDraft]:
    """Split `doc` into ≤`max_tokens` chunks with content-addressed IDs.

    Pure and deterministic: identical (tenant_id, doc, max_tokens) always
    yields identical chunk IDs. No I/O.
    """
    normalized = _normalize(doc.body_md)
    if not normalized:
        return []

    drafts: list[ChunkDraft] = []
    for piece in _split_blocks(normalized, max_tokens):
        content_hash = hashlib.sha256(f"{tenant_id}\n{piece}".encode()).hexdigest()
        drafts.append(
            ChunkDraft(
                id=content_hash,
                tenant_id=tenant_id,
                source_id=doc.provenance.source_id,
                content_md=piece,
                token_count=estimate_tokens(piece),
                provenance=doc.provenance,
                content_hash=content_hash,
            )
        )
    return drafts
