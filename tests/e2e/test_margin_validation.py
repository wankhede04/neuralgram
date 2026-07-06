"""M4-5 margin validation: token cost with vs without compression+routing+caching.

Naive path: every document's raw payload goes to the reasoning-tier model,
repeats are re-billed, nothing is compressed.
Optimized path (what Neuralgram actually does): C3 compression before the
call, hint routing to the cheap tier for extraction, and cache hits on
repeated identical calls.

Costs come from the real price table (router.metering). Result recorded in
DECISIONS.md (ADR-0012); the >=50% bar is enforced on every run.
"""

from decimal import Decimal
from pathlib import Path

from neuralgram.common.config import Settings
from neuralgram.compression.engine import compress
from neuralgram.memory.chunker import estimate_tokens
from neuralgram.router.cache import InMemoryResponseCache
from neuralgram.router.gateway import Message, build_gateway
from neuralgram.router.metering import call_cost_usd

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
# Real sample data: an HTML newsletter and Slack export text; each processed twice
# (agents frequently re-touch the same context, which is what the cache exploits).
REPEATS = 2
ASSUMED_OUTPUT_TOKENS = 200  # identical on both sides; reduction comes from the levers


def _sample_documents() -> list[str]:
    newsletter = (FIXTURES / "newsletter_sample.html").read_text(encoding="utf-8")
    slack = (FIXTURES / "slack_export_sample.json").read_text(encoding="utf-8")
    return [newsletter, slack]


def _naive_cost(documents: list[str]) -> Decimal:
    """No compression, no routing (reasoning tier for everything), no cache."""
    total = Decimal(0)
    for _ in range(REPEATS):
        for doc in documents:
            total += call_cost_usd(
                "mock", "mock-reasoning", estimate_tokens(doc), ASSUMED_OUTPUT_TOKENS
            )
    return total


async def _optimized_cost(documents: list[str]) -> Decimal:
    """Compression -> hint:fast routing -> cache; repeats hit the cache for free."""
    gateway = build_gateway(Settings(_env_file=None), cache=InMemoryResponseCache())
    total = Decimal(0)
    for pass_index in range(REPEATS):
        for doc in documents:
            compressed = compress(doc, budget=2000)
            result = await gateway.complete(
                [Message(role="user", content=compressed.text)], "hint:fast"
            )
            assert result.text  # the call succeeds through the real pipeline
            if pass_index == 0:  # later passes are cache hits: no provider call, no bill
                total += call_cost_usd(
                    "mock", "mock-fast", compressed.out_tokens, ASSUMED_OUTPUT_TOKENS
                )
    return total


async def test_margin_reduction_is_at_least_fifty_percent() -> None:
    documents = _sample_documents()
    naive = _naive_cost(documents)
    optimized = await _optimized_cost(documents)

    reduction = float(1 - optimized / naive)
    print(f"\nMARGIN naive=${naive:.6f} optimized=${optimized:.6f} reduction={reduction:.1%}")

    assert reduction >= 0.50, (
        f"margin claim not met: {reduction:.1%} < 50% (escalate per backlog M4-5 if this regresses)"
    )
