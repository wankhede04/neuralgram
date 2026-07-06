# Neuralgram — Autonomous Build Loop

**Operating manual for the building agent (Fable 5). Read this in full at the start of every iteration.**

You are building Neuralgram to a production-ready release by executing the loop in §3 repeatedly until the release checklist (§8) is green. You work in small, verifiable increments and you never proceed on a red gate.

---

## 1. Source-of-truth hierarchy

When two sources conflict, the higher one wins; if the conflict is material, **stop and escalate** (§6) rather than guess.

1. This manual (`neuralgram-BUILD-LOOP.md`) — *how* you work.
2. `neuralgram-product-spec.md` — *what* to build (components C1–C8, milestones M1–M5).
3. `neuralgram-engineering-standards.md` — stack, structure, quality bars.
4. `neuralgram-backlog.md` — the ordered work queue you consume.
5. The code and tests in the repo — the current reality.

## 2. Persistent state (survives between iterations)

You are stateless between runs. **All memory lives in the repo.** Maintain these:

- **`PROGRESS.md`** — current phase/milestone, task in flight, last CI result, open blockers, and a dated log. Template in §9. Update it every iteration.
- **`neuralgram-backlog.md`** — check off `[x]` tasks as they meet Definition of Done.
- **`DECISIONS.md`** — one short ADR (context / decision / consequence) for every non-trivial technical choice.
- **Git history** — the ground truth. Small, conventional commits (§ standards).

On startup, reconstruct context from these + `git log` + last CI status. Never assume in-memory state.

## 3. The loop — one iteration

```
1. LOAD      Read §1 sources + PROGRESS.md + `git status`/`git log -10` + last CI result.
2. SELECT    Pick the lowest-milestone, unblocked, unchecked task from the backlog.
             Respect declared dependencies. One task at a time.
3. GATE?     If the task touches a Human Gate (§6) that is unresolved → STOP, escalate, pick nothing else.
4. PLAN      Restate the task's acceptance criteria. Write a 3–8 step plan. Note files to touch.
5. IMPLEMENT Write the code AND its tests together. Keep the diff small and focused on this task only.
6. VERIFY    Run the full local gate (§5). All must pass:
                make fmt && make lint && make typecheck && make test && make security
             If anything is red → fix within this iteration. Do NOT commit red.
7. REVIEW    Self-review the diff against: acceptance criteria, §5 gates, security checklist,
             and "did I change anything outside this task's scope?" (revert scope creep).
8. COMMIT    Conventional commit. Update PROGRESS.md and check the backlog box.
             Add/append a DECISIONS.md entry if you made a design choice.
9. MILESTONE?If this task was the last in a milestone, run the milestone's Exit Criteria (§7).
             Only advance when they pass.
10. STOP?    If release checklist (§8) is fully green → open the release PR and HALT.
             Else loop back to step 1.
```

**Anti-thrash rule:** if the same test/gate fails on **3 consecutive iterations**, stop and escalate (§6). Do not keep guessing at the same wall.

## 4. Definition of Done (per task)

A task is done only when **all** hold:

- Acceptance criteria in the backlog are met and demonstrated by a test.
- New/changed code has tests; the suite is green.
- All §5 quality gates pass.
- Public interfaces have docstrings; user-facing behavior is documented if changed.
- No secrets, no TODOs left in the critical path, no scope beyond the task.
- `PROGRESS.md` and the backlog checkbox are updated; a DECISIONS.md ADR added if warranted.

## 5. Quality gates (must be green before any commit)

| Gate | Command (target) | Bar |
|---|---|---|
| Format | `make fmt` (ruff format) | no diff |
| Lint | `make lint` (ruff) | zero errors |
| Types | `make typecheck` (mypy strict on `src/`) | zero errors |
| Unit | `make test-unit` (pytest) | 100% pass; **≥85% coverage on core packages** (memory, compression, router) |
| Integration | `make test-int` (testcontainers: Postgres+pgvector, Redis) | 100% pass |
| Security | `make security` (secret scan + `pip-audit`/dep scan) | no high/critical, no secrets |
| Build | `make build` (Docker image) | image builds & boots healthcheck |

## 6. Human gates — STOP and escalate (do not proceed)

Write the blocker to `PROGRESS.md` under "BLOCKED", emit a concise escalation summary, and halt. These are decisions or risks you must not resolve autonomously:

- **D1 / D2 / D3 unresolved** and needed for the current task (memory ownership; model hosting; one-account legality). Use documented defaults only where the spec says so; otherwise stop.
- **Destructive or irreversible operations:** production data migration, data deletion, dropping columns/tables with data, key rotation.
- **New external cost or vendor:** enabling a paid provider, provisioning GPU/infra, anything that spends money.
- **Security-critical surfaces:** auth, tenant isolation model, secret handling, OAuth token storage — design must be reviewed before merge.
- **Ambiguous or contradictory acceptance criteria**, or a spec conflict (§1) you can't resolve cleanly.
- **Anti-thrash trip** (3× same failure).
- **Scope gap:** the backlog has no task covering work that's clearly required — propose the task, don't silently invent large scope.

## 7. Lifecycle phases & exit criteria

Advance only when the current phase's exit gate passes.

| Phase | Work | Exit criteria (gate) |
|---|---|---|
| **P0 — Scaffold** | Repo, tooling, CI, Docker, config, DB migration harness, health endpoint | CI green on empty app; `make build` boots; migrations run up/down; standards enforced in CI |
| **M1 — Spine** | C1 ingest → C2.1 chunk → C6 persist → C2.5 keyword search/fetch → C3 deterministic compression → C8 metering | Idempotent re-ingest proven; retrieval returns provenance; token-reduction metric recorded on real sample data; e2e test green |
| **M2 — Enrichment** | C2.2 queue+workers, C2.3 deep-score/embeddings/entities, C4 embed path, semantic search | Crash-recovery test (kill worker mid-job → job resumes); semantic search beats keyword on a fixture eval; queue dedupe/lease tested |
| **M3 — Memory trees** | C2.4 source/topic/global trees, hotness | Deterministic seal-cascade test; topic tree materializes only above hotness threshold; daily digest job runs on schedule; retrieval cost stays bounded as data grows (documented benchmark) |
| **M4 — Routing & margin** | C4 full hint routing, metering, spend caps, failover, caching | Hint→model resolution tested; per-tenant spend metered & capped; provider failover test; **50–80% token-cost reduction validated on real data & written to DECISIONS.md** |
| **M5 — Hardening** | C7 tenancy, RBAC, audit, GDPR erasure; C8 dashboards/alerts | Tenant isolation test (tenant A cannot read B); erasure cascade test; audit log of memory queries; alerts fire in a chaos test |
| **Release** | §8 checklist | All boxes green; release PR opened |

## 8. Production release checklist

- [ ] All milestone exit criteria (§7) passed.
- [ ] Security review complete; no high/critical findings; tenant isolation & authz tested.
- [ ] Load/soak test at target volume; retrieval latency SLO met; no memory/connection leaks.
- [ ] Backups + tested restore for Postgres and the vault store.
- [ ] Migrations reversible; rollback procedure documented and rehearsed.
- [ ] Observability: dashboards for ingest throughput, queue depth, retrieval latency, token cost/tenant; alerts wired.
- [ ] Runbook: deploy, rollback, on-call, incident, data-erasure (GDPR) procedures.
- [ ] Cost model validated against real usage; per-tenant caps enforced.
- [ ] Secrets in a manager (not env files in repo); rotation documented.
- [ ] `README`, API docs (OpenAPI), and `DECISIONS.md` current.
- [ ] Governing decisions D1/D2/D3 recorded as resolved in `DECISIONS.md`.

## 9. `PROGRESS.md` template

```markdown
# Neuralgram — Progress

## Now
- Phase/Milestone: <e.g. M2 — Enrichment>
- Task in flight: <backlog ID + title>
- Last CI: <pass/fail + link/sha>

## Blocked
- <none | gate + what you need from a human>

## Governing decisions
- D1 memory ownership: <unset|personal|org>
- D2 model hosting: <hybrid default|...>
- D3 brokering legality: <pending|allowed|restricted>

## Log (most recent first)
- YYYY-MM-DD — <task done / decision / blocker> (<commit sha>)
```

## 10. Hard rules (never violate)

Never commit on a red gate. Never commit secrets. Never run destructive/irreversible ops without a human gate. Never expand scope beyond the selected task. Never mock away an integration test that the milestone requires to be real. Never hand-edit a generated migration. Never mark a task done without a passing test that proves it.