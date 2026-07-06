# Neuralgram — Engineering Standards

The non-negotiable *how*. The build loop enforces these via CI. Deviations require a `DECISIONS.md` ADR.

---

## 1. Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11 | matches all-thing-eye |
| Web/API | FastAPI + Uvicorn | async; OpenAPI auto-docs |
| Data models | Pydantic v2 | validation at boundaries |
| DB | Postgres 16 + **pgvector** | primary store + embeddings |
| ORM / migrations | SQLAlchemy 2.x + Alembic | migrations are code-reviewed, reversible |
| Queue | start Postgres-backed (SKIP LOCKED); Redis/RQ if load demands | decision logged in ADR |
| Cache | Redis | prompt/response + hot reads |
| Model access | single gateway module (C4) | no direct provider SDK calls elsewhere |
| Packaging | `uv` (or Poetry) + `pyproject.toml` | lockfile committed |
| Lint/format | `ruff` (+ ruff format) | one tool |
| Types | `mypy --strict` on `src/` | |
| Tests | `pytest`, `pytest-asyncio`, `testcontainers` | real Postgres/Redis in integration |
| Container | Docker + docker-compose (dev) | multi-stage build |
| CI | GitHub Actions | gates from BUILD-LOOP §5 |
| Runtime | container on AWS (reuse all-thing-eye infra) | |

**Canonical Makefile targets** (the build loop's gates in BUILD-LOOP §5 map 1:1 to these): `fmt`, `lint`, `typecheck`, `test-unit`, `test-int`, `test` (= unit + integration), `security`, `build`.

## 2. Repository layout

```
neuralgram/
├── pyproject.toml  uv.lock  Makefile  docker-compose.yml  Dockerfile
├── README.md  PROGRESS.md  DECISIONS.md
├── neuralgram-product-spec.md  neuralgram-BUILD-LOOP.md  neuralgram-backlog.md
├── src/neuralgram/
│   ├── common/         # config, logging, errors, types, db session
│   ├── ingestion/      # C1 adapters + canonicalizer
│   ├── memory/         # C2: chunker, store, queue, workers, scoring, trees, retrieval
│   ├── compression/    # C3: classify, rules, reducers
│   ├── router/         # C4: gateway, providers, routing table, metering
│   ├── storage/        # C6: models, repositories, migrations glue
│   ├── observability/  # C8: tracing, metrics, cost meter
│   └── api/            # C5: FastAPI app, routes, auth, deps
├── migrations/         # Alembic
├── tests/{unit,integration,e2e,fixtures}/
├── ops/                # runbooks, dashboards, alert defs
└── .github/workflows/ci.yml
```

**Module boundary rule:** a component depends only via another component's public interface (the functions named in the spec). No reaching into internals. `router` is the *only* place that talks to model providers.

## 3. Configuration & secrets

- All config via `pydantic-settings`, sourced from env; typed `Settings` object, no bare `os.getenv` scattered around.
- Secrets never in the repo. Local dev uses `.env` (git-ignored); deployed uses a secret manager.
- A `MOCK_PROVIDERS=true` mode must let the whole pipeline run in dev/CI without real API keys (stubbed embeddings/completions with deterministic output).

## 4. Testing strategy

Pyramid, and every milestone's exit criteria (BUILD-LOOP §7) map to tests:

- **Unit** — pure logic: chunker determinism, hotness math, rule reducers, hint resolution. Fast, no I/O. ≥85% coverage on `memory`, `compression`, `router`.
- **Integration** — real Postgres+pgvector & Redis via testcontainers: persistence, queue lease/dedupe, migrations up+down, vector search.
- **Contract** — provider adapters tested against a mock server; assert request shape + response parsing per provider.
- **E2E** — the M1 spine and later flows end to end via the API with mocked providers.
- **Determinism fixtures** — canned inputs for tree seal-cascade and hotness so summarization logic is testable without nondeterministic LLM output (assert structure/state transitions, not prose).
- **Property tests** where valuable (chunk idempotency: same input → same IDs).

## 5. CI/CD pipeline (`.github/workflows/ci.yml`)

Stages, fail-fast, on every PR and on `main`:

`setup (cache deps) → fmt → lint → typecheck → unit(+coverage gate) → integration(services) → security(secret scan + pip-audit) → build(docker) → [main only] publish image`

- Coverage below threshold fails the build.
- No merge to `main` unless all stages green.
- Migrations checked: CI runs `alembic upgrade head` then `downgrade -1` on a scratch DB.

## 6. Version control & workflow

- **Trunk-based**: short-lived feature branches → PR → squash-merge to `main`.
- **Conventional Commits** (`feat:`, `fix:`, `test:`, `refactor:`, `chore:`, `docs:`); scope with component (`feat(memory): …`).
- One task per PR where practical; PR body restates acceptance criteria and links the backlog ID.
- **SemVer** tags; `main` is always releasable. Pre-1.0 during M1–M4; cut `1.0.0` at production release.
- Generated migrations are committed but never hand-edited after generation (regenerate instead).

## 7. Coding conventions

- Typed everywhere; `mypy --strict` clean. No `Any` without a comment justifying it.
- Pydantic models at every I/O boundary (API, provider, DB DTOs).
- Async I/O for DB/HTTP; no blocking calls in the event loop.
- Errors: typed exception hierarchy in `common/errors.py`; API maps them to problem+JSON responses; never swallow exceptions silently.
- Structured logging (JSON) with correlation/trace IDs; no `print`.
- Functions small and single-purpose; public APIs documented with docstrings that state inputs, outputs, and side effects.

## 8. Data & migrations

- Every schema change is an Alembic migration, reversible, reviewed.
- All tenant-scoped tables carry `tenant_id`; queries are tenant-filtered at the repository layer (enforced, not optional) — see C7.
- Retention/TTL and GDPR-erasure paths are implemented as first-class, tested operations (cascade chunks → scores → entities → summaries → vault files).
- Content-addressed chunk IDs (hash of normalized content) are the idempotency key; enforced by a unique constraint.

## 9. Observability (C8) — required from M1

- **Traces** (OpenTelemetry) spanning ingest → chunk → enrich → model call.
- **Metrics**: ingest throughput, queue depth, worker latency, retrieval latency (p50/p95), and per-call `tokens_in/out`, `reduction_pct`, `cost` tagged by tenant + hint.
- **The cost/margin dashboard** is the artifact that proves the 50–80% reduction claim; it is not optional.

## 10. Security baseline

- Secret scanning + dependency audit in CI; no high/critical merges.
- OAuth tokens (from all-thing-eye collectors) encrypted at rest; never logged.
- Tenant isolation has explicit tests (negative tests: cross-tenant reads fail).
- Model gateway strips/where-needed redacts sensitive fields before egress if D1/privacy policy requires.
- AuthN/Z on every API route; audit log for who queried whose memory.