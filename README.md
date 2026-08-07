# Neuralgram

A context engine: ingests multi-source data, folds it into durable + navigable memory,
compresses everything before it reaches a model, and routes each task to the right model.
Validated margin: **96.9% token-cost reduction** vs a naive pipeline (ADR-0012).

## API surface (OpenAPI: `docs/openapi.json`, live at `/docs`)

| Endpoint | Role | Purpose |
|---|---|---|
| `POST /auth/signup` | public | Self-serve: create a tenant + API key |
| `POST /auth/login` | public | Re-authenticate; issues a fresh key, invalidating the old one |
| `POST /memory/ingest` | writer | Canonicalize → compress → chunk → persist; async enrichment follows |
| `GET /memory/search?q=&mode=keyword\|semantic\|hybrid` | reader | Tenant-scoped retrieval with provenance |
| `GET /memory/chunks/{id}` | reader | Fetch one chunk + provenance |
| `GET /memory/summaries?tree=source\|topic\|global&scope_id=` | reader | Tree-scoped summaries (drill-down / topic / daily digest) |
| `GET /admin/audit` | admin | Who queried whose memory (key fingerprints) |
| `POST /admin/erase` | admin | GDPR erasure cascade for the caller's tenant |

Auth: `x-api-key` header → tenant + role (`API_KEYS` / `API_KEY_ROLES`, JSON env or
secrets dir; self-serve via `/auth/signup` also resolves through the same header).
Tenant isolation: fail-closed Postgres RLS + repository-layer scoping
(ADR-0014) — the app DB role must be **non-superuser**.

**Building a chatbot on top of Neuralgram?** See
[`docs/integration-guide.md`](docs/integration-guide.md) for a full
walkthrough: signup → ingest → a retrieval-augmented chatbot loop, with
runnable Python examples.

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
embeddings; no keys, no spend). Set `MOCK_PROVIDERS=false` with `ANTHROPIC_API_KEY`
(completions) and optionally `OPENROUTER_API_KEY` (embeddings, must output 384 dims —
see `.env.example`) for real model calls — an explicit cost decision (ADR-0013).

## Operations

- Runbooks: `ops/runbooks/` (deploy/rollback, on-call/incident, GDPR erasure, secrets rotation)
- Dashboard: `ops/dashboards/neuralgram.json` · Alerts: `ops/alerts.yml`
- Load/soak reports: `ops/reports/` · Load drill: `uv run python ops/loadtest/soak.py`

## Project documents

`docs/specification.md` (product spec) · `engineering-standards.md` ·
`executable-backlog.md` (work queue) · `build-loop.md` (build process) ·
`PROGRESS.md` (state) · `DECISIONS.md` (ADR log, 14 records incl. D1/D2/D3)

## License

Source-available under the [Elastic License 2.0](LICENSE) (ELv2) — **not**
OSI-approved "open source," by design. In practice:

- ✅ Free to read, run, modify, and **integrate into your own product** —
  this is the intended use case (see the integration guide above).
- ✅ Attribution is required: license and copyright notices must stay
  intact in any copy or derivative.
- ❌ You may not offer Neuralgram (or a derivative of it) to third parties
  as a hosted or managed service — i.e. no rebranded/competing SaaS built
  directly from this codebase.

See [`LICENSE`](LICENSE) for the full legal text.
