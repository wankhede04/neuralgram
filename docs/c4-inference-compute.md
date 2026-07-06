# Neuralgram — Product Specification

Version 0.1 · Status: Draft for engineering review
Scope of this document: **Part 0 (component map)** + **full spec for Component C4 — Inference & Compute (GPU/LLM)**. Other components will be specced in follow-up documents.

---

# Part 0 — Component Map

Neuralgram is a context engine. It divides into six functional components plus two cross-cutting concerns.

| ID | Component | One-line responsibility | Depends on |
|----|-----------|------------------------|------------|
| **C1** | Ingestion & Canonicalization | Pull from sources (reuse all-thing-eye collectors) → provenance-tagged Markdown | — |
| **C2** | Memory Tree | Chunk, score, queue, build source/topic/global summary trees, retrieval API, storage | C1, C3, C4 |
| **C3** | Compression Layer | Reduce tokens on every model-bound payload (rule overlay: classify→match→reduce) | C4 |
| **C4** | **Inference & Compute (this doc)** | Serve embeddings + LLM inference (self-hosted GPU and/or hosted API); expose one uniform inference interface | — |
| **C5** | Model Router | Map task hints → (provider, model); brokering, per-tenant metering, failover | C4 |
| **C6** | API & Service Layer | FastAPI service, RPC endpoints, auth, orchestration | C2, C5 |
| **C7** | Security, Multi-tenancy & Compliance | Tenant isolation, token storage, audit, GDPR (cross-cutting) | all |
| **C8** | Observability & Cost Metering | Metrics, tracing, token/GPU/cost dashboards (cross-cutting) | all |

```
C1 ─▶ C2 ─▶ (retrieval) ─▶ C6 ─▶ users/agents
      │  ▲
      ▼  │
     C3 ─┘   every model-bound call
      │
      ▼
     C5 (router) ──▶ C4 (inference: GPU + hosted API)
```

> **Build order ≠ document order.** In *build* order, C2 (Memory Tree) comes first because it defines the workload. C4's sizing numbers below are therefore **derived from assumptions about C2/C3 volume** and must be reconfirmed once those components exist. We spec C4 first only because it was requested; its parameters are inputs from C2/C3, not independent choices.

---

# Part 1 — Component C4: Inference & Compute Layer

## 1. Purpose

Provide **one uniform inference interface** for the rest of Neuralgram, backed by a mix of self-hosted open-weight models (on GPU) and hosted provider APIs. Every embedding and LLM call in the system goes through C4. C4 owns the models, the serving stack, the GPUs, and the decision of *where* each call physically runs. C5 (Router) decides *which logical model* to use; C4 decides *how and where* to execute it.

## 2. Responsibilities

**In scope:** model serving (LLM + embeddings), GPU provisioning and lifecycle, batching/queueing, quantization, autoscaling, self-host↔hosted failover, an OpenAI-compatible inference API, and per-call token/latency accounting emitted to C8.

**Out of scope:** deciding which model a task needs (C5), compressing payloads (C3), storing results (C2), business auth (C6).

## 3. Inputs / dependencies (⚠ assumptions to confirm with C2/C3)

The sizing in §6 assumes the following workload. **These are placeholders pending real all-thing-eye data rates.**

| Assumption | Placeholder value | Confirm from |
|---|---|---|
| Members (tenants) | 50 | Org |
| Admitted chunks/day/member | ~100 | C2 admit rate |
| Avg chunk size | ~1,000 tokens (bound ≤3,000) | C2 chunker |
| Extraction+summarization overhead | ~1.5× ingested tokens | C2 tree design |
| Interactive reasoning calls/day | low (hundreds) | C6 usage |
| Data-residency requirement | TBD — governs self-host vs hosted | C7 / legal |

Derived batch load: 50 × 100 × 1,000 × 1.5 ≈ **7.5M LLM input tokens/day** + ~5M embedding tokens/day.

## 4. Model inventory & tiering

Four inference roles. The router (C5) addresses these via hints (`hint:summarize`, `hint:reasoning`, `hint:vision`, plus embeddings); C4 backs each with a concrete model + location.

| Role | Volume | Latency need | Recommended model(s) | Location |
|---|---|---|---|---|
| **Embeddings** | Highest (every chunk) | Batch-tolerant | BGE-M3 / e5-large / Qwen3-Embedding (~0.5–2 B) | Self-host (tiny) or hosted |
| **Batch tier** (extraction, scoring, summary sealing) | High | Batch-tolerant | **Qwen3-8B / 14B**, **Gemma 3 12B** | **Self-host** |
| **Reasoning tier** (interactive agent turns) | Low | Interactive | Qwen3-32B, Gemma 3 27B, DeepSeek-R1-Distill-32B | Self-host (opt.) *or* hosted |
| **Flagship reasoning** (hardest turns) | Very low | Interactive | DeepSeek-V3/R1 671B-A37B, GLM-4.6 357B-A32B, Qwen3-235B-A22B | **Hosted API only** |
| **Vision** (screenshots/OCR) | Low | Interactive | Qwen-VL, Gemma 3 (multimodal) | Self-host or hosted |

**Model facts** (current, verified):
- **Qwen3**: dense 0.6/1.7/4/8/14/32B + MoE 30B-A3B, 235B-A22B; context 32K (small) to 128K (8B+).
- **Gemma 3**: 1/4/12/27B, 128K context, multimodal.
- **DeepSeek-V3/R1**: 671B total, **37B active** (MoE), 128K context.
- **GLM-4.5**: 355B/32B-active; **GLM-4.6**: 357B/32B-active, 200K context. Both large MoE.

**Design rule:** the batch tier does 90%+ of the token volume and does **not** need a smart model — self-host a small one. The flagships (DeepSeek-V3/R1, GLM-4.5/4.6, Qwen3-235B) are MoE models that still need *all* weights resident in VRAM (400 GB–1.4 TB) despite low active params — **never self-host these; reach them via API.**

## 5. Serving architecture

- **Engine:** vLLM (OpenAI-compatible server) for self-hosted models. TGI/SGLang acceptable alternatives; decision in §16.
- **Interface:** C4 exposes a single OpenAI-compatible `/v1/chat/completions` + `/v1/embeddings`. Self-hosted and hosted models sit behind the same contract so C5 is location-agnostic.
- **Batching:** continuous batching (vLLM native). Batch-tier calls are enqueued and processed with high concurrency; latency is not user-facing.
- **Quantization:** AWQ/INT4 for anything ≥14B (≈4× memory saving, ~2× speedup, minor quality loss). FP16 for the small batch model if VRAM allows.
- **Separation:** embeddings run as their own lightweight service (CPU or a small slice of GPU), decoupled from LLM serving so an embedding backlog can't starve summarization.

## 6. GPU sizing & provisioning

**VRAM = weights + KV cache + overhead.** Weights = params × bytes (FP16 = 2 B, INT4 ≈ 0.5 B). [Certain — arithmetic]

| Model | Params | Weights FP16 | Weights INT4 | Min GPU |
|---|---|---|---|---|
| Embedding (BGE-M3 etc.) | 0.3–2 B | <4 GB | — | CPU / 1× 8–24 GB shared |
| Qwen3-8B / Gemma 3 12B | 8–12 B | 16–24 GB | 5–7 GB | **1× 24 GB** (L4 / A10 / 4090) |
| Qwen3-14B | 14 B | ~28 GB | ~9 GB | 1× 24–48 GB |
| Qwen3-32B / Gemma 3 27B | 27–32 B | ~54–64 GB | ~18 GB | **1× 80 GB** (A100/H100) |
| Qwen3-72B / Distill-70B | 70–72 B | ~140 GB | ~40 GB | 2× 80 GB |
| DeepSeek-V3/R1, GLM-4.6, Qwen3-235B | 235–671 B | 470 GB–1.4 TB | 150–400 GB | 8× H100/H200 — **don't self-host** |

**Throughput** (vLLM, aggregate w/ batching) [Likely — vendor benchmarks]: on A100 80GB, 7B ≈ **3,360 tok/s**, 14B ≈ **3,000 tok/s**, 32B ≈ **580 tok/s**. H100 is higher. Interactive single-stream on a 32B ≈ 20–40 tok/s.

**Worked batch-tier estimate:** 7.5M tokens/day ÷ ~2,500 tok/s effective ≈ **~50 minutes of GPU-time/day**. [Guessing on volume, Likely on the ratio]

**Conclusion:**
- **Batch + embeddings:** a **single 24–48 GB GPU** covers it at a **low duty cycle** (bursty around ingest cycles). No cluster.
- **Reasoning tier:** if self-hosted, **one 80 GB GPU** for a quantized 32B; but given low volume, **routing to a hosted API is usually cheaper than owning the card.** Default = hosted, self-host only if C7 data-residency forbids it.
- **Flagship:** hosted API, always.
- **Baseline recommendation:** provision **1× 80 GB GPU** (or 1× 48 GB if reasoning stays hosted). Scale out only when measured volume demands it.

## 7. Functional requirements

- **FR-1** Expose OpenAI-compatible chat + embeddings endpoints; identical contract for self-hosted and hosted backends.
- **FR-2** Accept a resolved `(provider, model)` from C5 and execute it at the correct location.
- **FR-3** Continuous batching for batch-tier calls; priority lane for interactive calls so batch load never blocks a user turn.
- **FR-4** Emit per-call metrics to C8: model, location, input/output tokens, latency, GPU/queue state, estimated cost.
- **FR-5** Support model hot-swap / registry update without full service restart.
- **FR-6** Fall back to a configured hosted model if the self-hosted backend is unavailable (§11).

## 8. Non-functional requirements

- **Throughput:** sustain the confirmed batch load with ≥50% headroom.
- **Latency:** interactive reasoning turn P95 < 5 s to first token (target; depends on model + location).
- **Availability:** 99.5% for the inference interface (achieved via hosted fallback, not GPU redundancy).
- **Cost ceiling:** ≤ $X / active user / month (set with Finance; C8 enforces alerts).
- **Utilization:** GPU idle time is acceptable and expected — do **not** over-provision to keep GPUs busy.

## 9. Interface contract (sketch)

```
POST /v1/chat/completions   { model, messages, max_tokens, ... }  → OpenAI schema
POST /v1/embeddings         { model, input[] }                    → OpenAI schema
GET  /v1/models             → available models + location + health
# Internal: every response carries usage{input_tokens, output_tokens} + x-neuralgram-location header
```

## 10. Scaling & autoscaling

- Batch tier is **bursty** → scale-to-zero or scale-down between ingest cycles; wake on queue depth. Spot/pre-emptible GPUs are acceptable for batch (work is retryable via C2's job queue).
- Interactive tier (if self-hosted) needs a warm replica — cold starts break latency SLO. Otherwise route interactive to hosted (no warm-GPU cost).
- Horizontal scale = add vLLM replicas behind the endpoint; C4 load-balances.

## 11. Failover & fallback

Priority chain per role: **self-hosted replica → alternate self-hosted → hosted provider A → hosted provider B.** Health checks per backend; automatic demotion on error-rate/timeout. Because C2 work is retryable, a total GPU outage degrades to "slower + more expensive via API," not "down."

## 12. Security & data residency

- Data-residency policy (C7) is the deciding input: if member data may not leave infrastructure, the batch tier **must** be self-hosted and hosted APIs are restricted to non-sensitive payloads.
- Hosted-provider keys stored in secrets manager, never in code/config repos.
- Per-tenant request tagging for the audit trail (C7/C8).

## 13. Observability & metrics (emit to C8)

Tokens in/out per call, per tenant, per model; GPU utilization + VRAM; queue depth + wait time; tokens/sec; cost/call and cost/tenant/day; fallback activations; error rates by backend. **Cost-per-tenant is the margin dashboard** — first-class, not optional.

## 14. Configuration

- **Model registry** (declarative): for each logical model → {location, engine, quantization, GPU pool, max context, cost/1k tokens}. C5's route table references registry entries by name.
- Hot-reloadable; no recompile to remap a role to a different model.

## 15. Deployment topology

- **Dev:** stub/mock inference mode (no GPU, no keys) so engineers can run C1–C3/C6 end-to-end. **Required** — see acceptance criteria.
- **Staging:** 1 small GPU (24–48 GB) + hosted keys.
- **Prod:** 1× 80 GB GPU baseline (cloud on-demand or reserved; on-prem if C7 requires), + hosted providers for reasoning/flagship/fallback. Scale per measured load.

## 16. Risks & open questions

- **Hosted-reseller ToS** (from C5): if brokering hosted access is disallowed, the fallback + flagship strategy changes. **Resolve before relying on it.**
- **Engine choice:** vLLM vs TGI vs SGLang — benchmark on our actual batch model before committing.
- **Embeddings host:** local (residency-safe, tiny GPU/CPU) vs hosted (simplest). Tie to C7.
- **Self-host reasoning at all?** Only if residency forbids hosted. Otherwise skip the 80 GB card.
- **Real volume unknown** — every number in §3/§6 is a placeholder until C2 produces data rates.
- **On-prem vs cloud GPU** — capex vs opex decision with Finance; low duty cycle favors cloud/spot.

## 17. Acceptance criteria

1. A single OpenAI-compatible endpoint serves both a self-hosted model and a hosted model, selected by the `(provider, model)` passed in.
2. Batch-tier throughput sustains the confirmed load with ≥50% headroom on the provisioned GPU.
3. Killing the self-hosted backend transparently fails over to a hosted model with no dropped requests.
4. Every call emits accurate token + cost metrics to C8.
5. Dev mock-mode runs the full pipeline with no GPU and no provider keys.

## 18. Milestones

- **M1** — Stand up vLLM serving one batch model + an embeddings service behind the OpenAI-compatible interface; mock-mode for dev.
- **M2** — Wire hosted providers behind the same interface; implement failover chain.
- **M3** — Metrics/cost accounting to C8; load-test against placeholder volume; produce a sized, costed GPU recommendation from *real* C2 data rates.
- **M4** — Autoscaling / scale-to-zero for the batch tier; quantization tuning.

---

*Sizing figures are grounded in current vendor specs and vLLM benchmarks (see Sources in the chat message). All volume-derived numbers are explicitly placeholders pending real all-thing-eye data.*