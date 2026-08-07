# Integration Guide: Connect Your Chatbot to Neuralgram

This guide walks through wiring your own chatbot to Neuralgram so its
responses are grounded in a corpus of prior conversation history, instead
of relying only on what the model already knows. By the end you'll have a
working retrieval-augmented chatbot loop: ingest some history once, then
on every user message, pull relevant context from Neuralgram and feed it
into your own LLM call.

This guide is Python-only and uses raw HTTP calls (`requests`) — no SDK
required. It assumes you already have a Neuralgram instance running (see
the root `README.md` for `docker compose up` setup) and reachable at
`http://localhost:8000`.

## Prerequisites

- Python 3.11+
- An Anthropic API key, **for your own chatbot's LLM calls** — this is
  separate from and unrelated to your Neuralgram API key from Step 1 below.
- `pip install requests anthropic`

## Step 1: Get your API key

Sign up for a Neuralgram account. This creates an isolated tenant for your
data and returns an API key.

```sh
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "a-strong-password"}'
```

```json
{
  "api_key": "<your-generated-api-key>",
  "tenant_id": "user-<your-generated-tenant-id>",
  "role": "writer"
}
```

**Save the `api_key` now — it's shown exactly once.** There's no way to
retrieve it again later; if you lose it, call `POST /auth/login` with the
same email/password to get a fresh one (this invalidates the old key).

## Step 2: Ingest conversation history

Before your chatbot can retrieve anything useful, Neuralgram needs some
data. Here's a small example ingesting a Slack-shaped export:

```python
import requests

API_KEY = "your-api-key-from-step-1"
BASE_URL = "http://localhost:8000"

response = requests.post(
    f"{BASE_URL}/memory/ingest",
    headers={"x-api-key": API_KEY},
    json={
        "source_id": "support-channel-2026-08",
        "source_type": "slack",
        "payload": {
            "messages": [
                {
                    "user": "alice",
                    "text": "Our refund policy is 30 days from purchase, no questions asked.",
                    "ts": "1754500000.000100",
                },
                {
                    "user": "bob",
                    "text": "For enterprise customers we extend that to 90 days.",
                    "ts": "1754500060.000100",
                },
                {
                    "user": "alice",
                    "text": "Shipping usually takes 3-5 business days within the US.",
                    "ts": "1754500120.000100",
                },
            ]
        },
    },
)
print(response.status_code)  # 200
print(response.json())       # {'documents': 3, 'chunks_inserted': 3, 'chunks_skipped': 0}
```

**Important:** the `ts` field must be a **Unix epoch timestamp as a
string** (e.g. `"1754500000.000100"`), not an ISO-8601 datetime. Passing
something like `"2026-08-06T10:00:00Z"` will fail with a `500` error.

Ingest returns immediately, but enrichment (extraction, embedding
generation, summarization) happens in the background. Wait a few seconds
before searching for newly ingested content.

## Step 3: Build the retrieval-augmented chatbot loop

This is the core pattern: on every user message, search Neuralgram for
relevant context, then hand that context to your own LLM call.

```python
import anthropic
import requests

NEURALGRAM_API_KEY = "your-api-key-from-step-1"
NEURALGRAM_URL = "http://localhost:8000"

claude = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


def fetch_context(query: str, limit: int = 5) -> str:
    response = requests.get(
        f"{NEURALGRAM_URL}/memory/search",
        headers={"x-api-key": NEURALGRAM_API_KEY},
        params={"q": query, "mode": "hybrid", "limit": limit},
    )
    response.raise_for_status()
    chunks = response.json()
    if not chunks:
        return ""
    return "\n\n".join(f"- {chunk['content_md']}" for chunk in chunks)


def chat(user_message: str) -> str:
    context = fetch_context(user_message)

    system_prompt = (
        "You are a helpful support assistant. Answer using ONLY the context "
        "below. If the context doesn't cover the question, say you don't know."
        f"\n\nContext:\n{context}"
    )

    reply = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return reply.content[0].text


if __name__ == "__main__":
    print(chat("What's your refund policy for enterprise customers?"))
```

**Why `mode=hybrid`?** It fuses keyword and semantic search results, which
handles both exact-term matches ("refund policy") and paraphrased queries
("can I get my money back") better than either mode alone.
`mode=semantic` and `mode=keyword` are also available on the same endpoint
if you want to trade off differently — e.g. `keyword` is cheaper (no
embedding call) if your queries always share vocabulary with the source
text.

## Step 4: Running it end-to-end

With the two scripts above run in order (ingest, then the chatbot loop),
asking `"What's your refund policy for enterprise customers?"` produces:

```
For enterprise customers, the refund policy is 90 days from purchase, no questions asked.
```

Note that this answer correctly combines two separate ingested messages
(alice's general 30-day policy and bob's enterprise-specific 90-day
exception) — that's the retrieval step doing its job, not something
hardcoded in the prompt.

## Error handling

- **`401 Unauthorized`** — your `x-api-key` header is missing, wrong, or
  was invalidated by a subsequent `/auth/login` call (which rotates the
  key). Get a fresh key by logging in again.
- **`422 Unprocessable Entity`** on `/memory/ingest` — usually the `ts`
  field format from Step 2, or an unsupported `source_type` (only
  `"slack"` is supported today).
- **Empty search results right after ingest** — enrichment is
  asynchronous; wait a few seconds and retry.

## What's next

- The full endpoint reference, including `/memory/chunks/{id}` and admin
  endpoints, is available as interactive Swagger docs at
  `http://localhost:8000/docs`.
- For more advanced retrieval than a flat search, `/memory/summaries`
  exposes rolled-up summary trees — per-source drill-down, per-topic
  summaries, and daily digests — built automatically as you ingest more
  data.
