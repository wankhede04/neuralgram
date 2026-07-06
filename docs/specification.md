# Neuralgram — Product Specification

**Version:** 0.1 (draft for build kickoff)
**What Neuralgram is:** a context engine that ingests multi-source data, folds it into durable + navigable memory, compresses everything before it reaches a model, and routes each task to the right model. It is the intelligence layer on top of all-thing-eye's existing data collection.

> **Clean-room notice.** This spec and all implementation are original work. Any prior-art referenced during design informs architectural *ideas* only — never third-party code — to keep the codebase free of licensing entanglements.

---

## 0. Governing decisions (parameters, not blockers)

The spec is written so build can start before these close, but each has a marked impact. **Resolve before the milestone that depends on it.**

| # | Decision | Options | Blocks |
|---|---|---|---|
| **D1** | Whose memory is it? | Personal (per-user, private) **/** Organizational (shared/management lens) | Data model tenancy, access control, GDPR posture (C7) |
| **D2** | Where do models run? | Hosted APIs only **/** Hybrid (self-host batch tier, API for reasoning) **/** Fully self-hosted | Router config (C4), infra/GPU sizing |
| **D3** | One-account brokering legal? | Allowed / Restricted by provider ToS | Router billing model (C4) |

**Working defaults (used throughout unless changed):** D1 = build tenant-aware so either works; D2 = hybrid; D3 = pending legal, design router to support both brokered and BYO-key.

---

## 1. System overview

```
      ┌────────────── C1 Ingestion & Canonicalization ──────────────┐
      │  all-thing-eye collectors (Slack/GitHub/Notion/Drive) [reuse]│
      │  → normalize to provenance-tagged Markdown                   │
      └──────────────────────────────┬───────────────────────────────┘
                                      ▼
 ┌──────────────────────── C2 Memory Core ─────────────────────────┐
 │  C2.1 Chunker & content store                                    │
 │  C2.2 Job queue & workers                                        │
 │  C2.3 Scoring / embeddings / entity extraction                   │
 │  C2.4 Summary trees (source / topic / global)                    │
 │  C2.5 Retrieval API                                              │
 └───────────────┬─────────────────────────────────┬────────────────┘
                 │                                   │
                 ▼                                   ▼
        C3 Compression layer               C4 Model router & gateway
        (rule engine, pre-LLM)             (hint→model, metering, failover)
                 │                                   │
                 └─────────────────┬─────────────────┘
                                   ▼
        C5 Service / API layer (FastAPI, auth, RPC)
        C6 Storage layer (Postgres + pgvector, migrations, retention)
        C7 Security, multi-tenancy & compliance   [cross-cutting]
        C8 Observability & cost metering           [cross-cutting]
```

**Stack:** extend all-thing-eye — Python 3.11, FastAPI, Postgres (+pgvector), Redis, Docker/AWS. Not Rust/Tauri.

---

## 2. Component specifications

### C1 — Ingestion & Canonicalization

**Purpose:** turn raw source data into a uniform, provenance-tagged Markdown stream.
**Responsibilities:** reuse all-thing-eye collectors; normalize each source's output to Markdown; attach provenance (source, author, timestamp, URL/ID); hand off to C2.
**Interface:** `ingest(source_id, raw_payload) -> [CanonicalDoc]` where `CanonicalDoc = { body_md, provenance, source_type }`.
**Depends on:** all-thing-eye collectors, C3 (compress large source payloads before canonicalize where huge).
**Decisions:** fetch cadence (all-thing-eye default 24h may be too slow for "always current" — parameter); which sources ship in v1 (driven by D1 + first use case).

### C2 — Memory Core

The product. Five sub-components.

#### C2.1 Chunker & content store
**Purpose:** split canonical docs into bounded, addressable units.
**Rules:** ≤3k-token chunks (configurable); chunk ID = hash(normalized content) → **idempotent, dedup-free re-ingest**; write chunk row (C6) + `.md` file to the vault store in one transaction; mark `pending_extraction`.
**Interface:** `chunk(CanonicalDoc) -> [Chunk]`, `persist([Chunk]) -> txn`.
**Non-functional:** hot path is **synchronous and LLM-free**; bounded single-transaction write (no dangling rows on crash).

#### C2.2 Job queue & workers
**Purpose:** run all expensive work asynchronously and durably.
**Job kinds:** `extract_chunk`, `append_buffer`, `seal`, `topic_route`, `digest_daily`, `flush_stale`.
**Semantics:** each job has kind, payload, **unique dedupe key**, retry count, lease + expiry, `run_after`. Lease expiry on crash → job returns to queue. Worker pool (default 3) with a **semaphore capping concurrent model-bound calls**.
**Interface:** `enqueue(job)`, worker loop `claim() → run() → ack()/retry()`.
**Decision:** queue backend — Redis (Celery/RQ) vs Postgres-backed queue (keeps lease/dedupe transactional with data). Recommend Postgres-backed for consistency; revisit under load.

#### C2.3 Scoring, embeddings & entity extraction
**Purpose:** decide what's worth keeping and enrich it.
**Flow:** `fast-score` (heuristic, in hot path) gates cheap; `extract_chunk` worker does deep-score + embedding + entity extraction → `admitted` or `dropped`.
**Interface:** `deep_score(Chunk) -> {score, entities[], embedding}`.
**Model use:** embeddings via C4 (`hint:embed`), extraction via `hint:fast`. **Highest-volume model consumer** — primary target for C3 compression and D2 self-hosting.

#### C2.4 Summary trees
**Purpose:** compression + navigation over time.
**Three trees:** *source* (per source; L0 buffer → seal L1 → L2…), *topic* (per hot entity, materialized when `hotness > threshold`; `hotness = Σ mentions × recency_decay`), *global* (one daily digest node, enqueued 00:00 UTC).
**Leaf lifecycle:** `pending_extraction → admitted → buffered → sealed` (+ `dropped`). Chunk row survives drop for provenance.
**Interface:** `seal(buffer) -> Summary`, `route_topic(leaf)`, `digest(day)`.
**Model use:** `hint:summarize`.

#### C2.5 Retrieval API
**Purpose:** answer queries at any scope with provenance.
**Operations:** `search(query, scope)` (semantic + keyword), `drill_down(source_id)`, `topic(entity)`, `global(date)`, `fetch(chunk_id)`.
**Guarantee:** every result links back to its source chunk/`.md` for provenance.
**Consumer:** the agent/app layer built on Neuralgram (out of scope here).

### C3 — Compression layer
**Purpose:** cut tokens before any model call; protect margin.
**Pipeline:** `classify(payload)` → `match_rule` (3-layer overlay: builtin < user < project; JSON; hot-reloadable) → `reduce` (compose transforms to a token budget).
**Reducers:** deterministic first (HTML→Markdown, dedup, fold whitespace, drop-regex, truncate head/tail); LLM-summarize only if still over budget (`hint:summarize`). **Grapheme-safe** (never byte-split multibyte text).
**Interface:** `compress(payload, budget) -> {text, in_tokens, out_tokens, rule}`.
**Non-functional:** every call logs reduction metrics to C8.
**Applies at:** C2.3 extraction inputs, C2.4 summary inputs, and any tool/source payload entering a model.

### C4 — Model router & gateway
**Purpose:** send each task to the right model; single integration point for all model access.
**Resolution:** `model` = concrete name → default provider; or `hint:{reasoning|fast|vision|summarize|code|embed}` → route table → `(provider, model)`. Route table **remappable at runtime**.
**Gateway responsibilities:** provider adapters (Anthropic/OpenAI/Google/Groq + self-hosted endpoint), **per-tenant usage metering & cost attribution**, failover/retry across providers, per-tenant rate/spend caps, prompt/response caching.
**Interface:** `complete(messages, model_or_hint, opts) -> {text, usage, provider}`; `embed(texts) -> vectors`.
**Decisions:** D2 (which tier self-hosts), D3 (brokered vs BYO-key billing). Self-hosted endpoint is just another provider adapter (e.g., vLLM/Ollama-compatible).

### C5 — Service / API layer
**Purpose:** expose Neuralgram to callers; own auth and request lifecycle.
**Responsibilities:** FastAPI app; RPC/REST endpoints (`memory.ingest`, `memory.search`, `memory.fetch`, admin/status); authn/z (reuse all-thing-eye's web3-wallet admin auth + per-tenant scoping); request tracing to C8.
**Interface:** OpenAPI-documented endpoints mapping to C2.5 + C1 triggers.

### C6 — Storage layer
**Purpose:** durable, queryable persistence.
**Stores:** Postgres for `chunks, scores, entities, chunk_entities, summaries, jobs`; **pgvector** for embeddings; object store or filesystem for the `.md` vault.
**Schema (sketch):**
```
chunks(id, tenant_id, source_id, content_md, token_count, provenance, lifecycle, content_hash, created_at)
scores(chunk_id, fast_score, deep_score, hotness, embedding vector)
entities(id, tenant_id, name, type, hotness, last_seen); chunk_entities(chunk_id, entity_id)
summaries(id, tenant_id, tree_type, scope_id, level, body_md, child_ids, sealed_at)
jobs(id, kind, payload, dedupe_key UNIQUE, retry_count, lease_owner, lease_expires_at, run_after, status)
```
**Responsibilities:** migrations, retention/TTL, archival, GDPR-erasure paths (cascade across chunks→scores→entities→summaries).
**Decision:** pgvector sufficiency vs dedicated vector DB (Qdrant/Weaviate) at scale — measure, defer.

### C7 — Security, multi-tenancy & compliance *(cross-cutting)*
**Purpose:** isolate tenant data; meet legal obligations.
**Responsibilities:** tenant isolation model (row-level security vs schema-per-tenant vs DB-per-tenant — pick per D1); OAuth token storage/rotation (harden all-thing-eye's); RBAC; **audit trail of who queried whose memory**; GDPR/employee-monitoring compliance if D1 = organizational.
**Depends on:** D1 (dominant driver), C6.

### C8 — Observability & cost metering *(cross-cutting)*
**Purpose:** know what it costs and whether it's healthy.
**Responsibilities:** per-call token in/out + reduction % (from C3); per-tenant spend (from C4); ingest throughput, queue depth, retrieval latency SLO; tracing across C1→C2→C4; the "margin dashboard."
**Why first-class:** the 50–80% cost-reduction claim is validated *here*. No metering = no economic proof.

---

## 3. Non-goals (v1)

Fully autonomous multi-step task execution; new data collectors (reuse all-thing-eye's); desktop app / mascot / voice; fully self-hosted flagship models (DeepSeek-V3/R1, large GLM/Qwen MoE — API-only); multi-region.

---

## 4. Build sequence (dependency-ordered)

| Milestone | Delivers | Components | Proves |
|---|---|---|---|
| **M1 — Spine** | Ingest → chunk → persist → **keyword** `search`/`fetch`; **deterministic** compression instrumented (no model calls yet) | C1, C2.1, C2.5 (lexical), C3 (deterministic), C5, C6, C8 | Idempotent ingest; retrieval w/ provenance; measured token reduction on real data |
| **M2 — Enrichment** | Job queue, deep-score, embeddings, entities, semantic search | C2.2, C2.3, C4 (embed) | Durable async pipeline; crash recovery; semantic retrieval |
| **M3 — Memory trees** | Source → topic → global summaries; hotness | C2.4 | Bounded cost as history grows; navigable summaries |
| **M4 — Routing & margin** | Full hint routing, metering, caps, caching | C4 (complete) | Cost-per-task down; validated 50–80% claim |
| **M5 — Hardening** | Tenancy, RBAC, audit, GDPR erasure | C7 | Ship-ready for chosen D1 direction |

**Rule:** M1 before anything else — a searchable, provenance-backed, cost-instrumented chunk store is already useful and de-risks the rest. Summaries (M3) come *after* enrichment because they consume embeddings/entities.

---

## 5. Open decisions log

- **D1** memory ownership (personal vs org) — **owner: leadership** — blocks C7, gates M5.
- **D2** model hosting (hosted/hybrid/self) — **owner: eng** — gates infra + C4 config.
- **D3** one-account legality — **owner: legal** — gates C4 billing model.
- Queue backend: Redis vs Postgres-backed (C2.2).
- Vector store: pgvector vs dedicated (C6).
- Fetch cadence: 24h vs faster (C1).
- Real data volumes (chunks/day, avg size) — needed to size workers, GPU, DB growth.

---

## 6. Glossary

**Chunk** — a ≤3k-token, content-addressed unit of canonical Markdown. **Leaf** — an admitted chunk entering a summary tree. **Seal** — compressing an L0 buffer into an L1 summary. **Hotness** — decayed mention-frequency score that gates topic-tree materialization. **Hint** — a task label (`hint:reasoning`) the router resolves to a model. **Provenance** — the source/author/timestamp trail attached to every chunk.