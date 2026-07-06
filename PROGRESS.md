# Neuralgram — Progress

## Now
- Phase/Milestone: **P0 — Scaffold**
- Task in flight: **P0-2 Docker & compose** (next unchecked backlog item)
- Last CI: local gate green (fmt/lint/typecheck/test-unit/test-int/security) — CI pipeline lands in P0-3

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
- 2026-07-06 — P0-1 done: uv/pyproject scaffold, Makefile gates, src/neuralgram skeleton, /health + test; full local gate green. ADR-0001 (uv), ADR-0002 (detect-secrets + pip-audit).
- (seed) — Instruction package authored (spec, standards, backlog, build-loop). Ready to begin P0-1.