# Neuralgram — Progress

## Now
- Phase/Milestone: **M1 — Spine**
- Task in flight: **M1-7 API surface (C5)** (next unchecked backlog item)
- Last CI: remote CI green on main (P0 exit gate passed); local gate green for M1-1

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