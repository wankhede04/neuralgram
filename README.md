# Neuralgram

A context engine: ingests multi-source data, folds it into durable + navigable memory,
compresses everything before it reaches a model, and routes each task to the right model.
Validated margin: **96.9% token-cost reduction** vs a naive pipeline (ADR-0012).

## API surface (OpenAPI: `docs/openapi.json`, live at `/docs`)

| Endpoint | Role | Purpose |
|---|---|---|
| `POST /memory/ingest` | writer | Canonicalize → compress → chunk → persist; async enrichment follows |
| `GET /memory/search?q=&mode=keyword\|semantic\|hybrid` | reader | Tenant-scoped retrieval with provenance |
| `GET /memory/chunks/{id}` | reader | Fetch one chunk + provenance |
| `GET /memory/summaries?tree=source\|topic\|global&scope_id=` | reader | Tree-scoped summaries (drill-down / topic / daily digest) |
| `GET /admin/audit` | admin | Who queried whose memory (key fingerprints) |
| `POST /admin/erase` | admin | GDPR erasure cascade for the caller's tenant |

Auth: `x-api-key` header → tenant + role (`API_KEYS` / `API_KEY_ROLES`, JSON env or
secrets dir). Tenant isolation: fail-closed Postgres RLS + repository-layer scoping
(ADR-0014) — the app DB role must be **non-superuser**.

## Development

Requires Python 3.11, [uv](https://docs.astral.sh/uv/), and Docker (integration tests
use testcontainers: Postgres+pgvector, Redis).

```sh
uv sync                 # install dependencies
make fmt lint typecheck # style + types (mypy --strict)
make test               # unit + integration + e2e + combined coverage gate (>=85%)
make security           # secret scan + dependency audit
make build              # docker image (multi-stage, non-root, healthcheck)
uv run uvicorn neuralgram.api.app:app --reload   # run locally
docker compose up       # app + Postgres(pgvector) + Redis
```

Dev/CI run with `MOCK_PROVIDERS=true` (deterministic mock model + feature-hashed
embeddings; no keys, no spend). Enabling a real provider = configure its API key —
an explicit cost decision (ADR-0013).

## Operations

- Runbooks: `ops/runbooks/` (deploy/rollback, on-call/incident, GDPR erasure, secrets rotation)
- Dashboard: `ops/dashboards/neuralgram.json` · Alerts: `ops/alerts.yml`
- Load/soak reports: `ops/reports/` · Load drill: `uv run python ops/loadtest/soak.py`

## Project documents

`docs/specification.md` (product spec) · `engineering-standards.md` ·
`executable-backlog.md` (work queue) · `build-loop.md` (build process) ·
`PROGRESS.md` (state) · `DECISIONS.md` (ADR log, 14 records incl. D1/D2/D3)
