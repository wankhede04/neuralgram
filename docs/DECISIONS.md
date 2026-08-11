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

### 4.2 Lifetime call limit for self-serve signups (`signup_call_limit`)

**Decision:** every self-serve signup tenant (a row in `users`) gets
exactly **3 lifetime real completion calls + 3 lifetime real embedding
calls, tracked independently, no reset** — enforced regardless of what
triggered the call (a direct user search, or a background job triggered
by their own earlier ingest). Static `.env` keys and the demo tenant are
structurally exempt (no `users` row to match against).

**Why lifetime, not a recurring quota:** the goal is "let someone try the
product with real AI once," not "give away a recurring free tier
forever" — a recurring quota would mean unlimited AI cost over a long
enough time horizon per free account; a lifetime cap bounds total
exposure per signup to a small, fixed number.

**Why it also blocks background-triggered calls:** ingest triggers
background embed/completion jobs (chunk embedding, extraction, buffer-seal
summarization). Confirmed as an intentional design choice — it's meant to
be a blunt *total AI usage* kill switch per tenant, not just a limit on
calls the user directly typed a request for. The tradeoff (accepted): a
single large ingest could exhaust the embed budget before the user ever
runs a search. Search itself stays usable afterward in `mode=keyword`
(no embed call, so it's never capped).

### 4.3 Per-IP isolation & rate limit for the unauthenticated demo

**Decision:** the public `/demo` page previously shared one tenant_id and
one API key across every visitor — meaning visitor A's ingested data was
visible to visitor B's search, and there was no cap on total requests
(only a 3-message-per-ingest-*call* cap). Fixed by:
- Deriving a **per-IP tenant** at auth time
  (`{demo_tenant_id}-{sha256(ip)[:12]}`) instead of one shared tenant —
  each visitor's data is now isolated by IP.
- A **Redis-backed atomic per-IP daily request cap**
  (`DemoIpRateLimiter`, default 8 requests/IP/day) — `INCR`+`EXPIRE` is
  atomic, so it's safe under concurrent requests/workers without extra
  locking.

**Why Redis and not an in-memory counter:** an in-memory Python dict would
not survive multiple uvicorn workers or app restarts, and would let each
worker process enforce its own independent (and therefore ineffective)
limit.

**Gap found and closed: the per-IP request count alone doesn't bound
cost.** An ingest request fans out into background jobs — each ingested
message triggers 1 embed call + 1 completion call (extraction), plus a
summarization completion every 8 accumulated messages — so a worst-case
abuser turns "8 requests/day" into roughly 6x that many real AI calls.
Worse, the demo tenant is structurally exempt from §4.2's lifetime cap
(no `users` row), and a plain exact-match `tenant_spend_caps` entry can
never catch it either, since every visitor now gets a distinct per-IP
tenant_id. Closed by an **aggregate dollar cap shared across the whole
demo family**: `UsageMeter` accepts `demo_tenant_prefix` +
`demo_spend_cap_usd`, and `check_cap` sums spend across every tenant_id
matching `{demo_tenant_prefix}%` (not just the exact one) before allowing
a call — so one visitor's spend counts against every other visitor's
shared budget, closing the IP-rotation loophole that a purely per-IP
limit can't.

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
