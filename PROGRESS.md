# Neuralgram — Progress

## Now
- Phase/Milestone: **M3 — Memory trees**
- Task in flight: **M3-4 Tree-scoped retrieval** (next unchecked backlog item)
- Last CI: remote CI green on main (M2 exit gate passed); local gate green for M3-1

## Blocked
- none

## Governing decisions
- D1 memory ownership: **unset** — not required until M5; do NOT start M5 tasks until resolved.
- D2 model hosting: **hybrid (working default)** — CI/dev run with `MOCK_PROVIDERS=true`; enabling any real provider is an external-cost gate.
- D3 brokering legality: **pending** — required before M4-2 (real provider adapters); halt there if still pending.

## Environment prerequisites (human to confirm before iteration 1)
- [ ] Git repo initialized; the four spec docs + this file + DECISIONS.md committed.
- [ ] Access to the all-thing-eye codebase for the collector reused in M1-2.
- [ ] `MOCK_PROVIDERS=true` set for local/CI so P0–M3 need no real API keys.

## Log (most recent first)
- 2026-07-06 — M3-3 done: DigestBuilder — one global node per (tenant, day), refreshed on re-run, none for empty days; DigestScheduler sleeps to 00:00 UTC and enqueues digest_daily per active tenant, idempotent via queue dedupe (tick twice → 0 new). Wired into lifespan + worker pool.
- 2026-07-06 — M3-2 done: hotness = Σ 0.5^(age/half-life) (pure, unit-tested incl. half-life property); TopicRouter recomputes hotness per mention and materializes/refreshes a topic tree node only above threshold 3.0 (cold entities: hotness stored, no node). Extraction enqueues topic_route per linked entity.
- 2026-07-06 — M2 exit gate confirmed on remote CI (run 28785512852 success). Milestone advanced to M3.
- 2026-07-06 — M3-1 done: SourceTree — admitted→buffered→sealed lifecycle, buffer-full seal to L1, recursive cascade to L2+ via sealed_at consumption, flush_stale for partial buffers; deterministic children-digest marker. Coverage bar moved to combined pyramid measurement (ADR-0010), now 97%.
- 2026-07-06 — M2-5 done; **M2 exit criteria met locally**: crash-recovery proven (M2-2), semantic+hybrid beat keyword on labeled eval (recall@1), queue dedupe/lease tested (M2-1). Mock embeddings upgraded to feature-hashed BoW (ADR-0009); hybrid search = RRF fusion; /memory/search gains mode=keyword|semantic|hybrid.
- 2026-07-06 — M2-4 done: extract_chunk job — C3-compressed input, gateway JSON verdict with deterministic heuristic fallback (ADR-0008), embedding persisted, entities+links written, lifecycle → admitted/dropped (threshold 0.3); dropped rows retain provenance. Ingest enqueues jobs + wakes pool; app lifespan runs the pool. Worker ack/fail now shielded from cancellation (graceful-stop race found by test).
- 2026-07-06 — M2-3 done: embed path — gateway embeddings persisted to scores.embedding (pgvector) via upsert; cosine-distance NN query proven; provider contract test suite (mock now, real adapters must join in M4-2). No real provider enabled (cost gate intact).
- 2026-07-06 — M2-2 done: WorkerPool (N=3 default) with handler registry, model-call semaphore, wake-on-ingest + polling fallback; crash recovery via lease expiry. Integration test kills a worker mid-job → job reclaimed and completed (status done, no lost admits); unit tests prove semaphore cap, wake, failure paths.
- 2026-07-06 — M1 exit gate confirmed on remote CI (run 28779930024 success). Milestone advanced to M2.
- 2026-07-06 — M2-1 done: Postgres-backed JobQueue (ADR-0007) — SKIP LOCKED claims, dedupe_key ON CONFLICT, lease expiry recovery, run_after scheduling, bounded retries→failed. Integration tests: dedupe, lease-expiry reclaim, deferred run_after, retry exhaustion, concurrent distinct claims.
- 2026-07-06 — M1-9 done; **M1 exit criteria met**: e2e spine green (ingest real sample → search → fetch), idempotent re-ingest asserted (0 new chunks), provenance on every result, token-reduction metric recorded on real sample data. e2e suite wired into make test + CI integration stage.
- 2026-07-06 — M1-8 done: Prometheus compression metrics (tokens_in/out counters + reduction_pct histogram, labeled by rule); compress() records them per call; ingest route now runs deterministic compression (high budget, no lossy truncation) so a real sample ingest shows reduction on /metrics.
- 2026-07-06 — M1-7 done: /memory/ingest, /memory/search, /memory/chunks/{id} with per-tenant API-key auth (ADR-0006, human-approved design). OpenAPI documents routes + security scheme; authz tests (401s, cross-tenant 404/empty); full API roundtrip + idempotent re-ingest proven against real Postgres.
- 2026-07-06 — M1-6 done: ChunkRetrieval (tenant-scoped repo) with Postgres full-text search (ts_rank ordered) and fetch(id); every result carries provenance + source link. Integration tests: hit with provenance/url, fetch provenance, cross-tenant isolation (search and fetch both blind to other tenants).
- 2026-07-06 — M1-5 done: C3 deterministic compression — classify (html/markdown/text), builtin rule overlay, reducers (HTML→MD, dedup, fold, drop-regex boilerplate, grapheme-safe truncate via \X clusters). Fixture shows ≥30% reduction; property test proves truncation never splits grapheme clusters; reduction metrics logged per call.
- 2026-07-06 — M1-4 done: ContentStore persists chunk rows + vault .md files in one transaction; ON CONFLICT DO NOTHING on content_hash makes re-ingest idempotent; partial-failure integration test proves no dangling rows or files (rollback + file cleanup). Hot path stays LLM-free.
- 2026-07-06 — M1-3 done: deterministic chunker, ≤max_tokens splits (paragraph-first, whitespace-preferring hard split), content-addressed IDs = sha256(tenant_id + normalized content) (ADR-0005). Hypothesis property tests: idempotent IDs, zero new IDs on re-ingest, cross-tenant non-collision, budget respected, multibyte intact.
- 2026-07-06 — M1-2 done: C1 canonicalizer with pluggable normalizer registry; Slack export shape first (ADR-0004 — all-thing-eye unavailable, human approved). Provenance (source/author/timestamp/id/url) attached and embedded in body_md; multibyte preserved; empty messages skipped.
- 2026-07-06 — P0 exit gate passed (remote CI green: all 7 stages incl. migrations up/down + image boot probe). Phase advanced to M1.
- 2026-07-06 — M1-1 done: chunks/scores/entities/chunk_entities/summaries/jobs models + reversible migration 0002; uq_chunks_content_hash and uq_jobs_dedupe_key enforced; integration test proves tables, dupe rejection, down/up clean.
- 2026-07-06 — P0-6 done: structlog JSON logging with OTel trace/span IDs, TracerProvider + FastAPI instrumentation (request → handler-route server span asserted in test), Prometheus registry at /metrics with request counter + latency histogram, x-request-id middleware.
- 2026-07-06 — P0-5 done: async SQLAlchemy engine/session, typed error hierarchy, Alembic async harness + reversible baseline migration (pgvector extension), TenantScopedRepository enforcing tenant_id structurally. Integration test proves up/down/up clean on real pgvector Postgres; CI migrations job now active.
- 2026-07-06 — P0-4 done: typed pydantic Settings (env-sourced, dev-safe defaults), ModelGateway with deterministic MockProvider (hash-derived complete/embed), real providers hard-gated behind RuntimeError. App boots key-free; 8 unit tests, 100% cov.
- 2026-07-06 — P0-3 done: GitHub Actions CI (lint/typecheck/unit+coverage/integration/migrations/security/build+boot-probe). Repo made private; main pushed; PR #1 green, PR #2 red-blocked and closed. Branch protection unavailable on free-plan private repo → ADR-0003 (procedural merge discipline).
- 2026-07-06 — P0-2 done: multi-stage Dockerfile (uv builder → slim non-root runtime, HEALTHCHECK), compose with pgvector Postgres 16 + Redis 7; image boots, /health 200, healthcheck green. Dev compose creds allowlisted in secret scan.
- 2026-07-06 — P0-1 done: uv/pyproject scaffold, Makefile gates, src/neuralgram skeleton, /health + test; full local gate green. ADR-0001 (uv), ADR-0002 (detect-secrets + pip-audit).
- (seed) — Instruction package authored (spec, standards, backlog, build-loop). Ready to begin P0-1.