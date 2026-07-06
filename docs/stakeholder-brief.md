# Neuralgram — Stakeholder Brief

**Neuralgram is a context engine: it turns the company's scattered data into a durable, always-current, low-cost memory that any AI agent can use instantly.**

*One-page brief for leadership. Read time: ~3 minutes.*

---

## The problem

AI agents are only as good as the context they're given. Today that context is a problem on two fronts:

- **Agents start cold.** Every time we point an AI at our work — Slack, GitHub, Notion, Drive — it has no memory of what came before. We spend effort re-explaining context that should already be known.
- **Context is expensive.** Feeding raw data (long threads, logs, documents) into an AI model costs money per use, and that cost grows as our history grows. Left unmanaged, the AI bill scales with the company.

We already collect the data (via all-thing-eye). What we lack is a layer that makes that data *usable and affordable* to reason over.

## What Neuralgram is

Neuralgram sits between our data and our AI models and does three things:

| It… | In plain terms | Business outcome |
|---|---|---|
| **Remembers** | Continuously organizes everything we connect into a self-updating, searchable memory — with a traceable link back to the original source | Agents are never "cold"; answers are current and verifiable |
| **Compresses** | Strips the noise out of data *before* it reaches an AI model | Sharply lower AI running cost (see below) |
| **Routes** | Automatically sends each task to the cheapest model capable of doing it, under one account | No per-tool AI subscriptions; lower cost, less complexity |

It is **infrastructure**, not a finished app. The same engine can power an internal assistant, a team-analytics tool, or future products — we build it once and reuse it.

## Why it matters

- **Speed to usefulness.** New agents get full context from day one instead of over weeks.
- **Cost control.** Benchmarks on comparable systems suggest a **50–80% reduction in AI token cost** through compression and routing. We will validate this against our own data early — it is the core economic argument for building this.
- **Trust.** Every answer traces back to its source, so we can see *why* the AI said what it said.
- **Leverage on what we already have.** Neuralgram is the intelligence layer on top of all-thing-eye's existing data collection — we extend, not rebuild.

## What Neuralgram is deliberately NOT

To keep scope honest: Neuralgram is **not** a fully autonomous agent that completes arbitrary tasks unsupervised — that reliability does not exist dependably today. Neuralgram makes AI *better informed and cheaper to run*. Autonomy is a separate, later question.

---

## ⚠️ Decision required from leadership

**Whose memory is Neuralgram — the individual's, or the organization's?**

This is the one choice that shapes everything else, and it cannot be deferred:

- **Personal ("second brain")** — each person's own memory, private to them. Simpler privacy posture, individual-productivity value.
- **Organizational ("team lens")** — a shared/management view across members (the all-thing-eye direction). Higher analytical value, **but** triggers employee-monitoring and GDPR obligations that must be designed in from the start, not bolted on.

The data model, access controls, and legal review all fork here. **We need a direction before build begins.**

## Risks we're tracking

- **"One account" model may face legal limits.** Reselling brokered access to AI providers can conflict with their terms. We are verifying this; if constrained, the cost model adjusts but the product still stands.
- **Privacy/compliance** (if we choose the organizational direction, above).
- **Focus discipline.** The temptation is to rebuild data plumbing we already own. The build must stay on the intelligence layer.

## What we're asking for

1. **A decision** on the memory-ownership question above.
2. **Approval to build the memory layer first** — it is the product; compression and routing are optimizations that follow.
3. **A legal check** on the one-account model, run in parallel so it doesn't block engineering.

*Next step after sign-off: a scoped build plan (first data sources, timeline, and the cost-reduction validation test).*