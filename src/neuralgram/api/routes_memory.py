"""Memory API routes (C5): ingest, search, fetch — all tenant-scoped."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from neuralgram.api.deps import require_tenant
from neuralgram.common.errors import UnsupportedSourceError
from neuralgram.compression.engine import compress
from neuralgram.ingestion.canonicalize import ingest as canonicalize
from neuralgram.memory.chunker import chunk
from neuralgram.memory.retrieval import ChunkRetrieval, RetrievedChunk

router = APIRouter(prefix="/memory", tags=["memory"])

Tenant = Annotated[str, Depends(require_tenant)]


class IngestRequest(BaseModel):
    """A raw source payload to canonicalize, chunk, and persist."""

    source_id: str
    payload: dict[str, Any]
    source_type: str = "slack"


class IngestResponse(BaseModel):
    """Counts describing what an ingest call did."""

    documents: int
    chunks_inserted: int
    chunks_skipped: int


@router.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(
    body: IngestRequest, tenant_id: Tenant, request: Request
) -> IngestResponse:
    """Canonicalize `payload`, chunk it, and persist rows + vault files atomically."""
    try:
        docs = canonicalize(body.source_id, body.payload, body.source_type)
    except UnsupportedSourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    store = request.app.state.content_store
    queue = request.app.state.queue
    budget = request.app.state.settings.ingest_compress_budget_tokens
    inserted = 0
    skipped = 0
    for doc in docs:
        compressed = compress(doc.body_md, budget)
        result = await store.persist(
            chunk(doc.model_copy(update={"body_md": compressed.text}), tenant_id)
        )
        inserted += result.inserted
        skipped += result.skipped
        for chunk_id in result.inserted_ids:
            await queue.enqueue("extract_chunk", {"chunk_id": chunk_id}, f"extract:{chunk_id}")
    if inserted:
        request.app.state.worker_pool.wake()
    return IngestResponse(documents=len(docs), chunks_inserted=inserted, chunks_skipped=skipped)


@router.get("/search", response_model=list[RetrievedChunk])
async def search_endpoint(
    tenant_id: Tenant,
    request: Request,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[RetrievedChunk]:
    """Lexical search over this tenant's chunks; results carry provenance."""
    factory = request.app.state.session_factory
    async with factory() as session:
        return await ChunkRetrieval(tenant_id).search(session, q, limit)


@router.get("/chunks/{chunk_id}", response_model=RetrievedChunk)
async def fetch_endpoint(chunk_id: str, tenant_id: Tenant, request: Request) -> RetrievedChunk:
    """Fetch one chunk by id within this tenant; 404 if absent or foreign."""
    factory = request.app.state.session_factory
    async with factory() as session:
        found = await ChunkRetrieval(tenant_id).fetch(session, chunk_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chunk not found")
    return found
