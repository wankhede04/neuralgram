# Neuralgram

A context engine: ingests multi-source data, folds it into durable + navigable memory,
compresses everything before it reaches a model, and routes each task to the right model.

See `docs/specification.md` for the product spec, `engineering-standards.md` for the
stack and quality bars, `executable-backlog.md` for the work queue, and `build-loop.md`
for the autonomous build process. Current state lives in `PROGRESS.md` and `DECISIONS.md`.

## Development

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                 # install dependencies
make fmt                # format (ruff)
make lint               # lint + format check
make typecheck          # mypy --strict on src/
make test               # unit + integration
make security           # secret scan + dependency audit
make build              # docker image
```

Run the API locally:

```sh
uv run uvicorn neuralgram.api.app:app --reload
```

Dev/CI run with `MOCK_PROVIDERS=true`; no real model-provider keys are required
until explicitly enabled (human gate).

<!-- CI verification: trivial change (P0-3 AC) -->
