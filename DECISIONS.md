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

## ADR-0003 — Merge discipline without GitHub branch protection (2026-07-06, P0-3)

**Context.** The remote repo was made private to protect internal product docs. GitHub
branch protection (required status checks) is not available on free-plan private repos
(HTTP 403 on the protection API), so a red PR is not hard-blocked from merging by GitHub.
**Decision.** Keep the repo private. CI runs all gates on every PR and on `main`; merge
discipline ("no merge unless all stages green", standards §5) is enforced by the build
loop's own rules rather than a GitHub setting. Revisit when the repo moves to an org or
paid plan — then enable required status checks for all seven CI jobs.
**Consequence.** The P0-3 criterion "a deliberately failing test blocks merge" is
satisfied procedurally (red check demonstrated on a verification PR, closed unmerged),
not mechanically. Risk of accidental red merges rests on process until protection is enabled.

## ADR-0004 — Canonicalizer built against Slack export shape (2026-07-06, M1-2)

**Context.** M1-2 calls for reusing an all-thing-eye collector, but that codebase is not
accessible from this environment (checked filesystem + GitHub account; escalated, human
chose to proceed without it).
**Decision.** Implement C1 against the standard Slack export payload shape (channel
messages with `ts`, `user`, `text`, optional `thread_ts`/`permalink`). The normalizer
registry keeps `source_type` pluggable so the real all-thing-eye collector payloads can
be wired in as additional normalizers when access exists.
**Consequence.** First supported source is Slack. When all-thing-eye access arrives,
add its payload shapes as normalizers and validate against real collector output —
tracked as a follow-up under M1-2 in the backlog.

## ADR-0005 — Chunk hash includes tenant_id (2026-07-06, M1-3)

**Context.** `chunks.content_hash` carries a global unique constraint (M1-1 AC). A pure
content hash would dedupe identical content *across tenants*: tenant B's ingest of text
tenant A already stored would be silently rejected — a correctness bug and an isolation
leak (insert failure reveals another tenant has the same content).
**Decision.** `content_hash = sha256(tenant_id + "\n" + normalized_content)`; chunk
`id == content_hash`. Idempotency stays per-tenant; the global unique constraint stands.
**Consequence.** Identical content is stored once per tenant (small duplication across
tenants) in exchange for strict tenant isolation of the dedupe behavior. Property tests
assert both idempotency and cross-tenant non-collision.

## ADR-0006 — M1 API auth: per-tenant API keys (2026-07-06, M1-7)

**Context.** Auth is a security-critical human gate (BUILD-LOOP §6). The spec's plan —
reuse all-thing-eye's web3-wallet auth — is impossible (codebase unavailable, ADR-0004).
Escalated; human chose per-tenant API keys for M1.
**Decision.** `x-api-key` header resolved to `tenant_id` via a Settings-sourced mapping
(env `API_KEYS`, JSON). Keys compared with `hmac.compare_digest`; missing/unknown key →
401; keys never logged; no default keys (empty map = no access). All /memory routes
require the dependency; tenant_id flows into the tenant-scoped repositories.
**Consequence.** Simple, testable tenant scoping for M1–M4. Key storage is env-based
(dev-grade): M5-1/M5-5 must replace this with the chosen D1-driven tenancy model and a
secret manager, including rotation.
