# Design, Security & Pricing Decisions

This document records the *why* behind Neuralgram's architecture, security
guardrails, and cost model — the decisions that aren't obvious just from
reading the code. It's a living log, not a spec; update it when a decision
changes.

---

## 1. Licensing

**Decision:** Elastic License 2.0 (ELv2), not a traditional OSI open-source
license (MIT/Apache).

**Why:** ELv2 is source-available — anyone can read, self-host, and modify
the code — but restricts offering Neuralgram itself as a competing hosted
service. This protects against a cloud provider repackaging the project
without contributing back, while still being permissive for the actual
target users (developers self-hosting or embedding it in their own
product).

**Implication:** Don't describe Neuralgram as "open source" in strict OSI
terms in marketing copy — "source-available" is the accurate term.

---

## 2. Model integration architecture

**Decision:** All LLM/embedding calls go through a single `ModelGateway`
(`router/gateway.py`), resolved via `hint:xxx` strings
(`reasoning|fast|vision|summarize|code|embed`) through a `RouteTable`,
rather than calling provider SDKs directly from feature code.

**Why:** One integration point means usage metering, spend caps, response
caching, and provider failover are all enforced in exactly one place —
feature code never needs to remember to check a budget or record usage.
It also means swapping or adding a provider (e.g. adding OpenAI
embeddings alongside OpenRouter) touches one file, not every call site.

**Providers in use:**
- **Completions:** Anthropic (`claude-haiku-4-5`) — Anthropic has no
  embeddings API.
- **Embeddings:** OpenRouter (`sentence-transformers/all-minilm-l6-v2`,
  384-dim to match the fixed pgvector column width) — currently free-tier.
  See §6 (Pricing) for the tradeoffs being evaluated here.
- **Mock providers** (`MOCK_PROVIDERS=true`, the dev/CI default): deterministic
  hash-based fakes, so tests and local dev never require real API keys or
  incur real cost.

---

## 3. Authentication & tenant isolation

**Decision:** Two key sources, checked in order: static `.env`-configured
keys (`API_KEYS`/`API_KEY_ROLES`) for admins/self-hosters, and DB-issued
keys from self-serve signup (`users` table) for everyone else. One user =
one tenant = one key.

**Why:** Static keys need to keep working for people who self-host with
their own `.env` (no signup flow forced on them), while a public-hosted
demo needs a self-serve path with no manual provisioning.

**Security properties:**
- API keys are never stored or logged in raw form — only a SHA-256
  fingerprint (`key_fingerprint`) is recorded, used as the audit-log actor.
  The DB stores a hash of the key (`hashed_key`), not the key itself.
  (`api/deps.py`, `api/security.py`)
- **Postgres Row-Level Security (RLS)** enforces tenant isolation at the
  database layer, not just in application code — even a bug in a query
  that forgets a `WHERE tenant_id = ...` clause fails closed rather than
  leaking cross-tenant rows (ADR-era decision, `common/db.py`).
- Roles are `reader < writer < admin`; `require_role()` is a dependency
  factory so route handlers declare their minimum role inline.

---

## 4. Guardrails against runaway AI cost

Three independent, layered mechanisms — each closes a different attack
surface. They compose rather than replace each other.

### 4.1 Hard dollar spend cap (`tenant_spend_caps`)

Pre-existing mechanism: an optional per-tenant USD ceiling, checked before
every metered call against the sum of `usage_events.cost_usd` for that
tenant. No entry in the config dict = no cap (`UsageMeter.check_cap`).

**Why a dollar cap and not just a call-count cap:** different call types
have wildly different costs (a `reasoning` completion vs. a cheap `embed`
call), so a single dollar ceiling is the only unit that's meaningful
across all of them for tenants that need a spend ceiling rather than a
usage-count ceiling.

### 4.2 Lifetime request limit for self-serve signups (`signup_call_limit`)

**Decision (revised):** every self-serve signup tenant (a row in `users`)
gets exactly **4 lifetime ingest calls + 4 lifetime AI-backed (semantic
or hybrid) search calls, tracked and capped independently, no reset**.
Static `.env` keys and the demo tenant are structurally exempt (no
`users` row to match against). Keyword search and summary lookups make
no AI call at all and are never capped, for either signup or demo
tenants (`UsageMeter.check_and_record_ingest_request` /
`check_search_ai_request_limit`).

**Why requests, not raw AI calls (this superseded an earlier version of
the cap):** the original mechanism counted raw provider calls — every
`hint:embed`/completion call, regardless of source — in two shared
buckets. That broke in two ways once exercised end-to-end: (1) one
ingest call fans out into *many* embed/completion calls internally (one
pair per chunk), so "4 embed calls" could be exhausted by a single
8-message ingest, nowhere near "4 ingest calls" as a user would count
them; and (2) ingestion and search shared the *same* embed bucket, so
running a couple of test searches silently ate into the budget meant for
ingestion (and vice versa), which is exactly what caused a real signup
account to unexpectedly hit its cap after only 2 semantic searches.
Fixed by moving to two independently-tracked action-level counters:
- **Ingest**: `check_and_record_ingest_request` is a single self-contained,
  atomic (own `tenant_lock`) check-and-increment, called once per
  `POST /memory/ingest`, in the route handler *before* any processing —
  so message count inside one call never affects the count.
- **Search**: the check lives *inside* `ModelGateway.embed`, gated on a
  `meter_hint == SEARCH_AI_HINT` marker the search route passes in —
  atomic under `embed`'s own existing `tenant_lock` (check → provider
  call → record, same lock scope as the dollar spend cap). Exactly one
  embed call happens per semantic/hybrid search, so counting these is
  equivalent to counting AI-backed search requests.

Both mechanisms were verified under 15-way concurrency (a limit of 3
never let more than 3 through in either path) — see
`test_concurrent_ingest_calls_never_exceed_the_signup_lifetime_cap` /
`test_concurrent_search_ai_calls_never_exceed_the_signup_lifetime_cap` in
`tests/integration/test_spend_caps.py`.

**Why lifetime, not a recurring quota:** the goal is "let someone try the
product with real AI once," not "give away a recurring free tier
forever" — a recurring quota would mean unlimited AI cost over a long
enough time horizon per free account; a lifetime cap bounds total
exposure per signup to a small, fixed number.

**On background-triggered AI calls (extraction, buffer-seal summarization):**
these are no longer separately capped by count at all — once an ingest
call is accepted (under the 4-call ingest cap), whatever background
processing it triggers is bounded only by the pre-existing dollar spend
cap (§4.1, opt-in per tenant), not by this mechanism. This is a
deliberate simplification: capping ingest at the *request* level already
bounds how much background work a signup tenant can ever trigger, so a
second, separate AI-call-count cap over that same background work would
be redundant complexity.

### 4.3 Per-IP isolation & rate limit for the unauthenticated demo

**Decision:** the public `/demo` page previously shared one tenant_id and
one API key across every visitor — meaning visitor A's ingested data was
visible to visitor B's search, and there was no cap on total requests
(only a 3-message-per-ingest-*call* cap). Fixed by:
- Deriving a **per-IP tenant** at auth time
  (`{demo_tenant_id}-{sha256(ip)[:12]}`) instead of one shared tenant —
  each visitor's data is now isolated by IP.
- A **Redis-backed atomic per-IP, per-category daily request cap**
  (`DemoIpRateLimiter`, default 8/day per category) — `INCR`+`EXPIRE` on a
  key scoped to `(ip, day, category)` is atomic, so it's safe under
  concurrent requests/workers without extra locking. `category` is
  `"ingest"` or `"search"` (semantic/hybrid only) — mirroring §4.2's
  split for signup tenants, keyword search and summaries are never
  metered through this limiter at all.

**Why Redis and not an in-memory counter:** an in-memory Python dict would
not survive multiple uvicorn workers or app restarts, and would let each
worker process enforce its own independent (and therefore ineffective)
limit.

**Gap found and closed: request count alone doesn't bound cost.** An
ingest request fans out into background jobs — each ingested message
triggers 1 embed call + 1 completion call (extraction), plus a
summarization completion every 8 accumulated messages — so a worst-case
abuser can turn a handful of ingest requests into many more real AI
calls. Worse, the demo tenant is structurally exempt from §4.2's
per-tenant caps (no `users` row), and a plain exact-match
`tenant_spend_caps` entry can never catch it either, since every visitor
now gets a distinct per-IP tenant_id. Closed by an **aggregate dollar cap
shared across the whole demo family**: `UsageMeter` accepts
`demo_tenant_prefix` + `demo_spend_cap_usd`, and `check_cap` sums spend
across every tenant_id matching `{demo_tenant_prefix}%` (not just the
exact one) before allowing a call — so one visitor's spend counts
against every other visitor's shared budget, closing the IP-rotation
loophole that a purely per-IP limit can't. This dollar backstop is
independent of, and stacks with, the per-category request counts above.

---

## 5. Concurrency correctness (closing a real race)

**Finding:** the two mechanisms in §4.1/§4.2 were originally
*check-then-act*: count existing usage, decide, then record — with no
atomicity between the check and the eventual `record()` call. Proved with
a test: 15 concurrent calls fired at once against a limit of 3 all
succeeded (a full bypass). A malicious actor could deliberately fire many
concurrent requests to blow past any cap before a single one was recorded.

**Fix:** `UsageMeter.tenant_lock` — a Postgres **session-level advisory
lock**, scoped per `tenant_id`, held across check → provider call →
record. Concurrent requests for the *same* tenant now serialize (queue
briefly); unrelated tenants are entirely unaffected and stay parallel.
Re-verified: 15 concurrent calls against a limit of 3 → exactly 3 succeed,
12 correctly blocked. Verified again at 50 concurrent.

**Second-order finding from the same fix:** holding a lock while blocked
waiting for it also holds a pooled DB connection open. Under an
adversarial burst against one tenant, that alone could exhaust the shared
connection pool and cause a denial-of-service for *unrelated* tenants —
a self-inflicted-DoS risk introduced by the very fix meant to stop cost
abuse. Closed by:
- A bounded `lock_timeout` (3s) so an excessive burst fails fast with a
  clean `429` (`TooManyConcurrentRequestsError`) instead of hanging.
- Sizing the connection pool up (`pool_size=20, max_overflow=30`, from
  SQLAlchemy's default `5+10`) so realistic concurrent load — including
  a single tenant's legitimate parallel background jobs — doesn't trip
  false-positive `429`s.

This is a permanent regression test, not just a one-off script:
`tests/integration/test_spend_caps.py::test_concurrent_calls_never_exceed_the_signup_lifetime_cap`.

---

## 6. Pricing model & provider cost tradeoffs

### 6.1 Current provider costs

- **Anthropic completions:** billed per-token by Anthropic directly, at
  whatever rate the configured model (`claude-haiku-4-5`) charges. Bounded
  by §4.1/§4.2's caps.
- **OpenRouter embeddings:** currently on OpenRouter's free tier
  (`sentence-transformers/all-minilm-l6-v2`). Free tiers on shared
  infrastructure carry real risk once concurrent usage rises — a rate
  limit or exhausted quota there fails every embed call for every tenant,
  not just the offending one.

### 6.2 Embedding provider alternatives evaluated (not yet switched)

Researched as a mitigation for the OpenRouter free-tier risk above:

| Provider | Free tier | Paid price /1M tokens | 384-dim support | Verdict |
|---|---|---|---|---|
| **Jina AI** | ~1–10M tokens (inconsistently documented), but only **2 concurrent requests** on the free tier | Prepaid packs | Yes, via truncation | **Rejected** — the concurrency cap is worse than the problem being solved |
| **OpenAI `text-embedding-3-small`** | None (pay-as-you-go) | **$0.02/1M tokens** | Yes, exact via `dimensions` param | **Recommended** — cheapest reliable option, already has a compatible adapter in the codebase |
| **Voyage AI** | 200M tokens one-time grant | $0.02–0.12/1M | Partial | Backup option |
| **Cohere Embed v4** | 1,000 calls/month, ~5 RPM | $0.12/1M | No confirmed 384 support | Not favored |
| **Google Gemini Embedding** | ~1,500 req/day | $0.15–0.20/1M | Truncatable to 768, not 384 | Not favored |
| **Self-hosted `all-MiniLM-L6-v2`** | Unlimited (own compute) | Just server cost | Native 384-dim | Strong option for a $0-marginal-cost, zero-external-rate-limit path |

**Cost math at realistic scale (OpenAI, if adopted):** at $0.02/1M tokens,
light usage (~5M tokens/month) costs ~$0.10/month; even fairly heavy usage
(~100M tokens/month) costs ~$2/month. The scenario where this "hits
hard" is either (a) genuine large-scale success, or (b) deliberate abuse
with no cap — and (b) is exactly what §4's guardrails already exist to
prevent, independent of which provider sits behind `hint:embed`. Switching
providers does not remove or replace those caps; they apply at the
gateway layer regardless of provider.

**Status: not yet implemented.** Decision pending — either (a) OpenAI as
the default hosted-demo embedding provider (cheap, exact 384-dim match,
near-zero integration effort via the existing OpenAI-compatible adapter),
or (b) self-hosting the embedding model for zero marginal cost and zero
external rate-limit exposure, at the cost of owning that infra.

### 6.3 Recommended safety net regardless of provider choice

- Set a `tenant_spend_caps` entry for **every** static/admin key in use,
  not just signup tenants — those are structurally exempt from §4.2's
  lifetime cap and currently rely entirely on §4.1 (which is opt-in per
  tenant, not a global default).
- Consider setting a provider-side account-wide hard budget limit (e.g.
  OpenAI's dashboard budget alert) as defense-in-depth in case an
  application-level cap ever has a bug.

---

## 7. Secrets hygiene

**Decision:** `detect-secrets` scans every commit in CI
(`make security`), baselined against `.secrets.baseline`. Test-only
placeholder credentials (fake hashes, throwaway passwords used only
inside a `TestClient` in-memory flow) are marked inline with
`# pragma: allowlist secret` rather than editing the shared baseline —
keeps the baseline reviewable and avoids baseline drift from unrelated
changes.

---

## 8. Git identity / provenance

**Decision:** all commits to this repository must have both author and
committer set to the `wankhede04` GitHub identity — never a
personal/other account — even when an AI agent or automation is doing the
committing. Verified explicitly (`git log --format='%an <%ae> | %cn <%ce>'`)
before every push, not just trusted from a subagent's self-report.

**Why:** provenance on a project intended for public/community visibility
matters — commit history should reflect the project's actual maintainer
identity, not whichever local tool happened to run the command.

---

## 9. Deployment stack and hardening for it

**Decision:** Vercel (frontend, static Vite build) + Neon (Postgres +
pgvector) + Upstash (Redis) + Render (backend, one Web Service running
the existing Docker image — no separate "worker" service, since the
background job processor is in-process `asyncio` tasks in the same
FastAPI app, started in its `lifespan`).

**Why one Render Web Service is enough, not a separate Background
Worker service:** confirmed Render Web Services are genuinely persistent,
always-on containers, not a serverless-per-request model — in-process
`asyncio` background loops keep running continuously for the life of the
instance regardless of HTTP traffic. No architecture change needed for
this to work.

**Confirmed, real risk found and fixed before deploying:** two bugs were
found by deliberately reproducing failure modes specific to this stack,
not by inspection alone:

1. **Silent worker death on a not-yet-ready DB.** `WorkerPool._worker_loop`
   had no error handling around its `claim()` call — one unhandled
   exception (e.g. the schema not existing yet at boot) permanently ended
   that worker task, with zero log output, for the life of the process.
   Reproduced locally (container started before migrations ran) and
   confirmed extraction jobs sat `queued` forever with no error visible
   anywhere. This is a materially *worse* risk on Render's free tier than
   it was locally, since Render's paid "Pre-Deploy Command" (which would
   gate traffic behind successful migrations) is confirmed **not
   available on the free tier** — so the same race can recur on every
   free-tier deploy, not just local first-boot.

   Fixed: `_worker_loop` now catches, logs, and backs off
   (`DEFAULT_CLAIM_ERROR_BACKOFF_SECONDS = 2.0`) on a `claim()` failure
   instead of dying. Re-verified by reproducing the exact failure again
   (container up before migrations) — workers logged `worker.claim_failed`
   repeatedly, then self-healed the moment the schema existed, with **no
   restart**, and successfully processed a real ingest end to end
   (confirmed via real Anthropic + Jina calls in the logs).

2. **Neon's autosuspend can kill already-open pooled connections.** Neon's
   free tier autosuspends its compute after inactivity; its own docs
   describe `"terminating connection due to administrator command"`
   occurring on already-open, previously-idle pooled connections, not
   just new connection attempts — a real risk for a persistent
   SQLAlchemy pool sitting behind a continuously-polling worker. Fixed by
   adding `pool_recycle=280` to `build_engine` (below Neon's 5-minute
   default suspend window), alongside the `pool_pre_ping=True` already in
   place.

**Confirmed, not a risk:** running multiple instances of this worker
simultaneously. Render's zero-downtime deploys run the new instance
*while the old one keeps serving* for up to several minutes, and
horizontally-scaled plans run multiple instances as steady state — so
multiple independent copies of the in-process worker WILL poll the same
Postgres job queue concurrently, as a normal, expected occurrence, not
an edge case. This is safe only because `JobQueue.claim()` already uses
row-level lease claiming (competing-consumers pattern) rather than any
in-memory coordination — verified this is the correct, standard
mitigation for that scenario.

**Accepted, not fixed:** Render's free-tier cold start (spins down after
15 minutes idle, ~30–60s to wake on the next request). This is a UX
tradeoff, not a correctness bug — no code change was made to work around
it; upgrading to Render's paid tier removes it with zero further changes.
