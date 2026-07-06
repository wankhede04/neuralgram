# Neuralgram — Decisions (ADR log)

Short records: context / decision / consequence. Newest last.

---

## ADR-0001 — Packaging with uv (2026-07-06, P0-1)

**Context.** Standards §1 allow `uv` or Poetry for packaging/dependency management.
**Decision.** Use `uv` with `pyproject.toml` + committed `uv.lock`; dev tools declared
in the `dev` dependency group; hatchling as the build backend for the `src/` layout.
**Consequence.** All gate commands run through `uv run`; CI installs with `uv sync`.
Faster resolution/installs than Poetry; contributors need uv installed (documented in README).

## ADR-0002 — Security gate: detect-secrets + pip-audit (2026-07-06, P0-1)

**Context.** BUILD-LOOP §5 requires a secret scan and a dependency audit; both must run
locally and in CI without extra system-level installs.
**Decision.** `make security` runs `detect-secrets-hook` against a committed
`.secrets.baseline` over all git-tracked files, then `pip-audit` on the resolved
environment. Both are pip-installable, so the gate is reproducible anywhere Python runs.
**Consequence.** New secrets fail the gate; known false positives are audited into the
baseline. High/critical advisories in dependencies block commits until resolved or pinned.
