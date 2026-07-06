# Neuralgram — Executable Backlog

The work queue the build loop consumes. Do tasks **top-to-bottom**; each lists acceptance criteria (AC) and dependencies (Dep). Check `[x]` only when Definition of Done (BUILD-LOOP §4) is met. IDs are stable; add tasks (don't renumber) if a gap is found — and escalate if the gap is large.

Legend: `Dep:` must be done first · `Gate:` triggers a human gate (BUILD-LOOP §6).

---

## Phase 0 — Scaffold

- [x] **P0-1 Repo & tooling** — pyproject/uv, ruff, mypy strict, pytest, Makefile targets (`fmt/lint/typecheck/test/security/build`). *AC:* `make lint typecheck test` runs green on empty app.
- [x] **P0-2 Docker & compose** — multi-stage Dockerfile; compose with Postgres+pgvector and Redis. *AC:* `make build` boots; `/health` returns 200. *Dep:* P0-1.
- [x] **P0-3 CI pipeline** — `.github/workflows/ci.yml` with all gate stages + coverage threshold + migration up/down check. *AC:* CI green on a trivial PR; a deliberately failing test blocks merge. *Dep:* P0-2.
- [x] **P0-4 Config & mock mode** — typed `Settings`; `MOCK_PROVIDERS=true` path. *AC:* app starts with no real keys; mock embed/complete return deterministic output. *Dep:* P0-1.
- [x] **P0-5 DB harness** — SQLAlchemy session, Alembic baseline migration, repository base with enforced `tenant_id` filter. *AC:* migration up/down clean; repo rejects un-scoped tenant queries in a test. *Dep:* P0-2.
- [x] **P0-6 Observability skeleton (C8)** — structured logging, OTel tracing, metrics registry, request/trace IDs. *AC:* a request emits a trace spanning API→handler; metrics endpoint live. *Dep:* P0-2.

**Exit:** BUILD-LOOP §7 P0 gate.

## M1 — Spine  *(C1, C2.1, C2.5-lexical, C3-deterministic, C5, C6, C8)*

- [x] **M1-1 Storage models (C6)** — `chunks`, `scores`(stub), `summaries`(stub), `jobs`(stub), `entities`(stub) + migration. *AC:* tables created; `chunks.content_hash` unique constraint. *Dep:* P0-5.
- [x] **M1-2 Canonicalizer (C1)** *(built against Slack export shape, ADR-0004; wire real all-thing-eye collector payloads when access exists)* — normalize a source payload → provenance-tagged Markdown; reuse an all-thing-eye collector for one source (pick per first use case). *AC:* given a sample payload, output Markdown carries source/author/timestamp/id. 
- [x] **M1-3 Chunker (C2.1)** — ≤3k-token split; content-addressed IDs. *AC (property test):* identical input → identical chunk IDs; re-ingest creates zero duplicates. *Dep:* M1-1, M1-2.
- [x] **M1-4 Content store + hot-path persist (C2.1/C6)** — single-transaction write of chunk rows + `.md` vault files; mark `pending_extraction`; **no LLM calls**. *AC:* partial-failure test leaves no dangling rows. *Dep:* M1-3.
- [x] **M1-5 Deterministic compression (C3)** — classify + rule overlay (builtin layer) + deterministic reducers (HTML→MD, dedup, fold, drop-regex, truncate); grapheme-safe. *AC:* reduction on a fixture payload; multibyte text preserved; metrics logged. *Dep:* P0-6.
- [x] **M1-6 Keyword retrieval (C2.5)** — `search`(lexical), `fetch(id)` with provenance. *AC:* query returns chunks with source links; `fetch` returns provenance. *Dep:* M1-4.
- [x] **M1-7 API surface (C5)** *(auth = per-tenant API keys, ADR-0006; revisit in M5)* — `POST /memory/ingest`, `GET /memory/search`, `GET /memory/chunks/{id}`; auth + tenant scoping. *AC:* OpenAPI docs; authz test. *Dep:* M1-6.
- [x] **M1-8 Cost/reduction metering (C8)** — record `tokens_in/out`, `reduction_pct` per compression call. *AC:* metric visible on dashboard for a real sample ingest. *Dep:* M1-5.
- [x] **M1-9 E2E spine test** — ingest real sample → search → fetch. *AC:* green e2e; idempotent re-ingest asserted. *Dep:* M1-7, M1-8.

**Exit:** BUILD-LOOP §7 M1 gate.

## M2 — Enrichment  *(C2.2, C2.3, C4-embed)*

- [x] **M2-1 Durable job queue (C2.2)** — Postgres-backed (SKIP LOCKED); kind/payload/dedupe-key/retry/lease/run_after. *AC:* dedupe prevents dup jobs; lease expiry returns job to queue. *Dep:* M1-1.
- [x] **M2-2 Worker pool** — N=3, semaphore caps concurrent model calls; woken by ingest, polling fallback; lease recovery on startup. *AC:* **crash-recovery test** — kill worker mid-job → job resumes, no lost admits. *Dep:* M2-1.
- [x] **M2-3 Router embed path (C4)** *(mock provider only; real embedding provider remains an external-cost gate)* — `embed(texts)` via gateway; mock in CI; `hint:embed`. `Gate:` enabling a real embedding provider = external-cost gate. *AC:* embeddings persisted to pgvector; contract test on adapter. *Dep:* P0-4.
- [x] **M2-4 Deep scoring + entity extraction (C2.3)** — `extract_chunk` job: deep-score + entities + embedding → `admitted`/`dropped`. *AC:* lifecycle transitions tested; dropped chunks retain provenance row. *Dep:* M2-2, M2-3.
- [x] **M2-5 Semantic search (C2.5)** *(BoW mock embeddings, ADR-0009; re-run eval when a real embed provider is enabled)* — vector + keyword hybrid retrieval. *AC (fixture eval):* semantic beats keyword-only on a labeled fixture set. *Dep:* M2-4.

**Exit:** BUILD-LOOP §7 M2 gate.

## M3 — Memory trees  *(C2.4)*

- [x] **M3-1 Source tree seal cascade** — L0 buffer → `seal` L1 → cascade L2…; `flush_stale`. *AC (determinism fixture):* buffer fills → seal fires; cascade asserted on state, not prose. *Dep:* M2-4.
- [x] **M3-2 Hotness + topic routing** — `hotness = Σ mentions × recency_decay`; `topic_route` gated by threshold. *AC:* topic tree materializes only above threshold; hotness math unit-tested. *Dep:* M3-1.
- [x] **M3-3 Global daily digest** — scheduler enqueues `digest_daily` at 00:00 UTC. *AC:* digest node built for a simulated day; scheduler idempotent. *Dep:* M3-1.
- [ ] **M3-4 Tree-scoped retrieval** — `drill_down`, `topic`, `global`. *AC:* each scope returns correct summaries with provenance. *Dep:* M3-2, M3-3.
- [ ] **M3-5 Cost-bounded growth benchmark** — measure retrieval/summarization cost as data grows. *AC:* documented benchmark shows bounded cost; written to DECISIONS.md. *Dep:* M3-4.

**Exit:** BUILD-LOOP §7 M3 gate.

## M4 — Routing & margin  *(C4 full)*

- [ ] **M4-1 Full hint routing** — route table for `reasoning/fast/vision/summarize/code/embed`; runtime remap; concrete-name fallthrough. *AC:* resolution unit-tested for each hint + fallthrough. *Dep:* M2-3.
- [ ] **M4-2 Provider adapters + failover** — ≥2 providers; health checks; automatic failover + retry/backoff. `Gate:` each real provider = external-cost + legality (D3). *AC:* failover test (primary down → secondary serves). *Dep:* M4-1.
- [ ] **M4-3 Per-tenant metering & spend caps** — real-time usage accounting; hard caps. *AC:* cap trips and blocks further spend in a test; usage attributed per tenant. *Dep:* M4-1, C8.
- [ ] **M4-4 Prompt/response caching** — cache layer over gateway. *AC:* cache hit measured; correctness preserved. *Dep:* M4-1.
- [ ] **M4-5 Margin validation** — end-to-end token cost with/without compression+routing on real data. *AC:* **50–80% reduction validated & recorded in DECISIONS.md**; if not met, escalate. *Dep:* M4-3, M4-4, M1-8.

**Exit:** BUILD-LOOP §7 M4 gate.

## M5 — Hardening  *(C7, C8)*  `Gate: D1 must be resolved before starting`

- [ ] **M5-1 Tenancy model** — implement isolation per D1 (RLS / schema-per-tenant / db-per-tenant). *AC:* **negative test** — tenant A cannot read tenant B under any endpoint. *Dep:* D1 resolved.
- [ ] **M5-2 RBAC + audit** — roles; audit log of who queried whose memory. *AC:* unauthorized access denied + logged; audit query returns trail. *Dep:* M5-1.
- [ ] **M5-3 GDPR erasure** — cascade delete across chunks/scores/entities/summaries/vault. *AC:* erasure test leaves no residue anywhere, including embeddings. *Dep:* M5-1.
- [ ] **M5-4 Dashboards & alerts (C8)** — ingest, queue depth, latency SLO, cost/tenant; alerts. *AC:* **chaos test** — induce failure, alert fires. *Dep:* C8 skeleton.
- [ ] **M5-5 Secrets hardening** — move to secret manager; rotation doc. *AC:* no secrets in repo/scan; rotation rehearsed. 

**Exit:** BUILD-LOOP §7 M5 gate.

## Release  `Gate: full checklist is a human sign-off`

- [ ] **R-1 Load/soak test** at target volume; latency SLO met; no leaks. *AC:* report in `ops/`.
- [ ] **R-2 Backup + restore** for Postgres and vault; rehearsed. *AC:* restore drill passes.
- [ ] **R-3 Rollback rehearsal** — migrations reversible; documented. *AC:* rollback drill passes.
- [ ] **R-4 Runbooks** — deploy/rollback/on-call/incident/erasure. *AC:* present in `ops/`.
- [ ] **R-5 Docs** — README, OpenAPI, DECISIONS.md current; D1/D2/D3 recorded resolved. 
- [ ] **R-6 Final security review** — no high/critical; isolation + authz signed off. `Gate:` human review.
- [ ] **R-7 Release PR + 1.0.0 tag** — open PR; HALT for human merge.

---

### Dependency spine (quick reference)
`P0 → M1 → M2 → M3 → M4 → M5 → Release`. Within a milestone, follow listed `Dep:`. D1 gates M5; D2 gates any real-model task in M2/M4; D3 gates M4-2.