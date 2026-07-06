# Neuralgram — Progress

## Now
- Phase/Milestone: **M1 — Spine**
- Task in flight: **M1-2 Canonicalizer (C1)** (next unchecked backlog item)
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
- 2026-07-06 — P0 exit gate passed (remote CI green: all 7 stages incl. migrations up/down + image boot probe). Phase advanced to M1.
- 2026-07-06 — M1-1 done: chunks/scores/entities/chunk_entities/summaries/jobs models + reversible migration 0002; uq_chunks_content_hash and uq_jobs_dedupe_key enforced; integration test proves tables, dupe rejection, down/up clean.
- 2026-07-06 — P0-6 done: structlog JSON logging with OTel trace/span IDs, TracerProvider + FastAPI instrumentation (request → handler-route server span asserted in test), Prometheus registry at /metrics with request counter + latency histogram, x-request-id middleware.
- 2026-07-06 — P0-5 done: async SQLAlchemy engine/session, typed error hierarchy, Alembic async harness + reversible baseline migration (pgvector extension), TenantScopedRepository enforcing tenant_id structurally. Integration test proves up/down/up clean on real pgvector Postgres; CI migrations job now active.
- 2026-07-06 — P0-4 done: typed pydantic Settings (env-sourced, dev-safe defaults), ModelGateway with deterministic MockProvider (hash-derived complete/embed), real providers hard-gated behind RuntimeError. App boots key-free; 8 unit tests, 100% cov.
- 2026-07-06 — P0-3 done: GitHub Actions CI (lint/typecheck/unit+coverage/integration/migrations/security/build+boot-probe). Repo made private; main pushed; PR #1 green, PR #2 red-blocked and closed. Branch protection unavailable on free-plan private repo → ADR-0003 (procedural merge discipline).
- 2026-07-06 — P0-2 done: multi-stage Dockerfile (uv builder → slim non-root runtime, HEALTHCHECK), compose with pgvector Postgres 16 + Redis 7; image boots, /health 200, healthcheck green. Dev compose creds allowlisted in secret scan.
- 2026-07-06 — P0-1 done: uv/pyproject scaffold, Makefile gates, src/neuralgram skeleton, /health + test; full local gate green. ADR-0001 (uv), ADR-0002 (detect-secrets + pip-audit).
- (seed) — Instruction package authored (spec, standards, backlog, build-loop). Ready to begin P0-1.