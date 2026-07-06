"""C3 compression engine: classify -> match rule -> reduce to a token budget.

Deterministic-only for M1 (no LLM summarize fallback yet — that arrives
with the router paths in M2+). Every call logs reduction metrics (C8).
"""

import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from neuralgram.compression import reducers
from neuralgram.memory.chunker import estimate_tokens
from neuralgram.observability import metrics
from neuralgram.observability.logging import get_logger

PayloadKind = Literal["html", "markdown", "text"]

_HTML_HINT = re.compile(r"<\s*(html|body|div|p|table|span|a|script|h[1-6])[\s>]", re.I)
_MD_HINT = re.compile(r"(^#{1,6}\s)|(\[[^\]]+\]\([^)]+\))|(^- )|(```)", re.M)

_BOILERPLATE_PATTERNS = [
    r"(?i)^\s*(unsubscribe|copyright ©|all rights reserved|sent from my)",
    r"(?i)cookie (policy|preferences)",
]

logger = get_logger(__name__)


class CompressionResult(BaseModel):
    """Outcome of one compress call, including token accounting for C8."""

    text: str
    in_tokens: int
    out_tokens: int
    rule: str


def classify(payload: str) -> PayloadKind:
    """Classify a payload as html, markdown, or plain text (cheap heuristics)."""
    if _HTML_HINT.search(payload):
        return "html"
    if _MD_HINT.search(payload):
        return "markdown"
    return "text"


_Transform = Callable[[str], str]

_BUILTIN_RULES: dict[PayloadKind, tuple[str, list[_Transform]]] = {
    "html": (
        "builtin:html",
        [
            reducers.html_to_md,
            lambda t: reducers.drop_regex(t, _BOILERPLATE_PATTERNS),
            reducers.dedup_lines,
            reducers.fold_whitespace,
        ],
    ),
    "markdown": (
        "builtin:markdown",
        [
            lambda t: reducers.drop_regex(t, _BOILERPLATE_PATTERNS),
            reducers.dedup_lines,
            reducers.fold_whitespace,
        ],
    ),
    "text": (
        "builtin:text",
        [reducers.dedup_lines, reducers.fold_whitespace],
    ),
}


def compress(payload: str, budget: int) -> CompressionResult:
    """Reduce `payload` to at most ~`budget` tokens using deterministic transforms.

    Applies the builtin rule for the classified payload kind, then
    grapheme-safe truncation only if still over budget. Logs in/out token
    counts and the applied rule.
    """
    kind = classify(payload)
    rule_name, transforms = _BUILTIN_RULES[kind]
    in_tokens = estimate_tokens(payload)

    text = payload
    for transform in transforms:
        text = transform(text)

    if estimate_tokens(text) > budget:
        text = reducers.truncate_to_tokens(text, budget)
        rule_name = f"{rule_name}+truncate"

    out_tokens = estimate_tokens(text)
    reduction_pct = round(100 * (1 - out_tokens / in_tokens), 2) if in_tokens else 0.0
    metrics.compression_tokens_in_total.labels(rule_name).inc(in_tokens)
    metrics.compression_tokens_out_total.labels(rule_name).inc(out_tokens)
    metrics.compression_reduction_pct.labels(rule_name).observe(reduction_pct)
    logger.info(
        "compression.applied",
        rule=rule_name,
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        reduction_pct=reduction_pct,
    )
    return CompressionResult(text=text, in_tokens=in_tokens, out_tokens=out_tokens, rule=rule_name)
