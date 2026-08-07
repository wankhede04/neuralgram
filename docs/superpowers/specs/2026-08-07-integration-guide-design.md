# Developer Integration Guide

## Problem

Neuralgram has no developer-facing walkthrough for the actual use case the
README pitches ("a memory layer for AI agents"). Everything so far has been
tested via Swagger by us directly; a third-party developer with their own
chatbot has no path to "how do I actually wire this into what I'm
building." This blocks any self-serve adoption (Product Hunt visitors,
early integrators).

## Goal

A single, self-contained doc — `docs/integration-guide.md` — that takes a
developer from zero to a working retrieval-augmented chatbot loop: get a
key, ingest some history, then on each user message pull relevant context
from Neuralgram and feed it into their own LLM call.

## Non-goals

- No SDK. Raw `requests` HTTP calls only. A Python SDK was discussed
  earlier in this project's history and is separate, future scope.
- No non-Python language examples (no curl-only fallback, no JS/Node).
- No MCP server / OpenAI-function-calling tool spec. That's a different
  integration shape (the chatbot's own LLM invoking Neuralgram as a tool)
  and out of scope here — this guide is "developer wires it by hand."
- No production hardening guidance beyond a one-line mention that
  `/auth/login` rotates the key. Rate limiting, retry/backoff strategies,
  and key-rotation automation are not covered.

## Audience

A developer already building a chatbot in Python (any framework or none),
who wants that chatbot's responses grounded in a corpus of prior
conversation history stored in Neuralgram.

## Structure

The guide is one linear walkthrough, in this order:

### 1. Prerequisites
Python 3.11+, an Anthropic API key (for the *reader's own* chatbot LLM
calls — explicitly distinct from Neuralgram's own key), `pip install
requests anthropic`.

### 2. Step 1: Get your API key
`POST /auth/signup` shown via curl (matches how a developer would first
touch the API, before writing any Python). Note the response is shown
**once** — save `api_key` and `tenant_id` immediately. Link to
`docs/superpowers/plans/2026-08-06-signup-login.md`'s spec is not
necessary here; keep this guide self-contained and not assume the reader
has seen our internal planning docs.

### 3. Step 2: Ingest conversation history
A runnable Python snippet POSTing a small Slack-shaped payload to
`/memory/ingest`. Explicitly calls out the `ts` field's Unix-epoch-string
requirement (not ISO-8601) — a real gotcha hit and debugged during this
project's own local testing, worth saving the reader the same trip. Note
that enrichment (extraction, embedding, summarization) happens
asynchronously after the call returns.

### 4. Step 3: Build the retrieval-augmented chatbot loop
The centerpiece. A runnable Python script defining `chat(user_message:
str) -> str` that:
1. Calls `GET /memory/search` with `mode=hybrid`, the user's message as
   `q`.
2. Formats the returned chunks (their `content_md` fields) into a context
   block.
3. Sends a system/context block plus the user's message to Anthropic's
   Messages API (`anthropic` Python SDK).
4. Returns Claude's response, now grounded in retrieved context.

Includes a short note on why `mode=hybrid` (keyword + semantic fusion) is
the default recommendation here, with a one-line mention that
`mode=semantic` and `mode=keyword` exist for different tradeoffs.

### 5. Step 4: Running it end-to-end
Expected sample output (a realistic transcript), so a reader who isn't
running the server themselves yet can still see what success looks like.

### 6. Error handling notes
What a `401` (invalid/expired key) and a `422` (malformed ingest payload,
e.g. the `ts` field mistake from Step 2) mean and how to fix them — real
errors this project's own team hit and debugged, not hypothetical ones.

### 7. What's next
Pointer to `/docs` (the live Swagger UI) for the full endpoint reference,
and a short mention that the summary-tree endpoints
(`/memory/summaries`) exist for more advanced use (drill-down, topic,
daily digest) beyond the basic search loop this guide demonstrates.

## Testing / verification

This is a documentation deliverable — "testing" means: every code snippet
in the guide must actually run against a live local Neuralgram instance
(the same `docker compose up` setup used throughout this project) before
the guide is considered done. No untested snippets.
