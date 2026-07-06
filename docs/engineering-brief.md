# Neuralgram — Engineering Brief

**Neuralgram is a context engine: it ingests multi-source data, folds it into a durable + navigable memory, compresses everything before it hits a model, and routes each task to the right model.** It is the intelligence layer on top of all-thing-eye's existing data collection.

This brief is written to be *attacked*. Assumptions are stated explicitly so you can challenge them. The open-questions section at the end is the point — extend it.

---

## 1. TL;DR for engineers

- Three components: **Memory Tree** (durable structured memory), **Compression** (token reduction before the LLM), **Routing** (task → model).
- **Proposed stack: extend all-thing-eye** — Python 3.11, FastAPI, Postgres, Redis, Docker/AWS. *Not* OpenHuman's Rust/Tauri. Reuse the existing plugin collectors and scheduler; don't rebuild ingestion.
- **This is mostly an I/O + orchestration + API-cost problem, not a GPU problem.** The only compute question is embeddings/local-model hosting (§6).
- Clean-room: OpenHuman is GPL3. We take the *architecture ideas*, not the code.

## 2. System shape

```
 all-thing-eye collectors (Slack / GitHub / Notion / Drive)  ← reused
        │  canonicalize → provenance-tagged Markdown
        ▼
 ┌─────────────── Neuralgram core (FastAPI service) ───────────────┐
 │  Ingest hot path  → chunk → fast-score → persist → enqueue   │
 │  Job queue (Redis/Celery OR Postgres-backed) + workers       │
 │  Summary trees: source / topic / global                      │
 │  Compression layer (rule overlay) on every model-bound call  │
 │  Model router (hint → provider/model) + usage metering       │
 └──────────────────────────────────────────────────────────────┘
        │                                   │
        ▼                                   ▼
  Postgres + pgvector                 Hosted model APIs
  (chunks, scores, summaries,         (via one brokered account)
   entities, jobs)                    + hosted embeddings OR local
```

## 3. Memory Tree (the core)

**Hot path (synchronous, no LLM):** canonicalize → chunk (≤3k tokens, content-addressed IDs) → cheap heuristic score → persist in one transaction → enqueue follow-up. Fast and crash-safe. Idempotent because chunk ID = hash of normalized content.

**Async workers** do the expensive work off a durable job queue: deep scoring, embeddings, entity extraction, summary sealing, daily digest. Lease-based so a crash returns unfinished jobs to the queue.

**Three summary trees:**
- *Source tree* — one per source; leaves fill an L0 buffer, seal into L1 → L2 as they fill.
- *Topic tree* — one per "hot" entity; materialized lazily when hotness clears a threshold.
- *Global tree* — one daily digest node, enqueued at 00:00 UTC.

**Leaf lifecycle:** `pending_extraction → admitted → buffered → sealed` (with a `dropped` branch). Chunk rows persist even when dropped, for provenance.

**Storage sketch (Postgres + pgvector):**
```
chunks(id, tenant_id, source_id, content_md, token_count, provenance, lifecycle, content_hash, created_at)
scores(chunk_id, fast_score, deep_score, hotness, embedding vector)
entities(id, tenant_id, name, type, hotness, last_seen) ; chunk_entities(chunk_id, entity_id)
summaries(id, tenant_id, tree_type, scope_id, level, body_md, child_ids, sealed_at)
jobs(id, kind, payload, dedupe_key UNIQUE, retry_count, lease_owner, lease_expires_at, run_after, status)
```

**Retrieval API:** `search` (semantic) · `drill_down` (source tree) · `topic` (entity) · `global` (digest) · `fetch(id)` (provenance).

## 4. Compression layer (the margin)

Sits on every model-bound payload (tool results + summarization inputs). Pipeline: **classify** (source/content type) → **match rule** (3-layer overlay: builtin < user < project, JSON, hot-reloadable) → **reduce** (compose transforms until under a token budget).

- Deterministic reducers first (HTML→Markdown, dedup lines, fold whitespace, drop-regex, truncate). No LLM.
- LLM summarize only if still over budget (routed via `hint:summarize`).
- Grapheme-safe (never byte-split CJK/emoji).
- **Instrumented:** log input/output tokens + reduction % per call. This is the margin dashboard.

## 5. Routing (the cost lever + legal risk)

`model` field takes a concrete name (`anthropic/claude-…`) or a hint (`hint:reasoning|fast|vision|summarize|code`). Hint resolves via a runtime-remappable route table to `(provider, model)`. **The agent loop emits the hint based on the task** — the task picks the model, not a human.

"One account" means we broker provider keys. That pulls in **per-tenant usage metering, cost attribution, failover across providers, rate/spend caps, and prompt caching** — and a **legal check** on whether reselling brokered access violates provider ToS. Flag, not blocker.

## 6. The compute / GPU question (decide explicitly)

The workload is API calls + Postgres I/O + rule-based text processing. GPU is **only** relevant for two optional choices:

- **Embeddings:** hosted embedding API (no GPU, cheap, data leaves the box) **vs** local embedding model (GPU or beefy CPU, data stays in). Volume = every admitted chunk.
- **Local LLMs:** if privacy requires on-prem inference (Ollama-style), then GPU sizing, batching, and throughput become real. Otherwise not needed.

Default assumption unless privacy dictates otherwise: **hosted APIs, no GPU fleet.** Challenge this if our data-residency posture says models must run in-house.

## 7. Stated assumptions (challenge these)

1. We extend all-thing-eye's Python/Postgres/Redis/Docker stack rather than starting fresh.
2. Hosted model + embedding APIs by default; no self-hosted GPU inference in v1.
3. Postgres + pgvector is sufficient as the vector store at our scale (not a dedicated vector DB).
4. Chunk bound = 3k tokens; worker pool small (≈3) with a semaphore capping concurrent LLM calls.
5. Auto-fetch cadence inherited from all-thing-eye (24h) — may be too slow for "always current."
6. Single-region deployment initially.

## 8. Open questions — seed list, please extend

**Infra & deployment**
- Job queue: reuse Redis (Celery/RQ) or a Postgres-backed queue for the lease/dedupe semantics described? Trade-offs?
- Where does the ingest hot path run — inside the FastAPI process, or a separate worker service?
- Single Postgres for everything, or split OLTP (jobs/chunks) from vector search load?
- Multi-tenant from day one, or single-tenant until the memory-ownership decision lands?

**Compute / GPU**
- Hosted vs local embeddings — what does our data-residency policy actually require?
- If local: which embedding model, what GPU, expected chunks/day, batch throughput?
- Do any privacy commitments force local LLM inference? If so, sizing and cost?

**Data & storage**
- pgvector vs dedicated vector DB (Qdrant/Weaviate) — at what data volume does pgvector hurt?
- Growth model: chunks/day × retention = DB size in 6/12 months? Archival/TTL policy?
- Re-embedding strategy when we change embedding models?
- How do we handle deletes/GDPR erasure across chunks, summaries, and derived entities?

**Model / API**
- Which providers in the route table at launch? Fallback order on outage?
- Prompt-caching strategy — per provider, or an app-level cache?
- How do we measure and cap per-tenant spend in real time?
- Reliability target for summarization quality — how do we regression-test summaries?

**Security & compliance**
- If organizational memory: employee-monitoring law + GDPR review — who owns it?
- OAuth token storage/rotation (inherited from all-thing-eye, or hardened)?
- Tenant data isolation model — row-level security, schema-per-tenant, or DB-per-tenant?
- Audit trail for who queried whose memory.

**Performance & scaling**
- Ingest throughput target (chunks/sec) and the retrieval latency SLO?
- What happens under a burst (e.g., a 10k-message Slack backfill)? Backpressure?
- Cost ceiling per active user per month — what's acceptable?

**Setup & DX**
- Local dev story: can an engineer run the full pipeline without provider keys (mock/stub mode)?
- Seed/fixture data for testing the tree seal + hotness logic deterministically?
- Feature flags for enabling components independently (memory without routing, etc.)?

## 9. Non-goals (v1)

- No fully-autonomous task execution.
- No self-hosted GPU inference unless privacy forces it.
- No new data collectors — reuse all-thing-eye's.
- No desktop app / mascot / voice (OpenHuman surface area we don't need).

## 10. Suggested first milestone

Ingest → chunk → persist → `search`/`fetch` retrieval, on Postgres+pgvector, with hosted embeddings and the compression layer instrumented — **no summary trees yet.** Prove: (a) idempotent ingest, (b) retrieval with provenance, (c) measured token reduction on real all-thing-eye data. Everything else builds on that spine.