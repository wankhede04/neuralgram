"""Unit tests for C3 deterministic compression (M1-5 acceptance)."""

from pathlib import Path

import regex
from hypothesis import given
from hypothesis import strategies as st

from neuralgram.compression.engine import classify, compress
from neuralgram.compression.reducers import (
    dedup_lines,
    drop_regex,
    fold_whitespace,
    truncate_to_tokens,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "newsletter_sample.html"


def test_classify_kinds() -> None:
    assert classify("<html><body><p>hi</p></body></html>") == "html"
    assert classify("# Title\n\n[link](https://example.com)") == "markdown"
    assert classify("just plain words") == "text"


def test_fixture_payload_is_reduced_and_multibyte_preserved() -> None:
    payload = FIXTURE.read_text(encoding="utf-8")
    result = compress(payload, budget=10_000)

    assert result.out_tokens < result.in_tokens
    reduction = 1 - result.out_tokens / result.in_tokens
    assert reduction >= 0.30, f"expected >=30% reduction on fixture, got {reduction:.0%}"
    assert result.rule == "builtin:html"

    assert "日本語のテキストも問題なく扱えます 🎉" in result.text
    assert "👨‍👩‍👧‍👦" in result.text
    assert "<p>" not in result.text and "<script" not in result.text
    assert "console.log" not in result.text
    assert "Unsubscribe" not in result.text
    assert "[runbook](https://example.com/runbook)" in result.text
    assert result.text.count("Welcome to the digest") == 1


def test_over_budget_payload_is_truncated_and_rule_tagged() -> None:
    payload = "word " * 4000
    result = compress(payload, budget=100)
    assert result.out_tokens <= 100
    assert result.rule.endswith("+truncate")


@given(st.text(min_size=1), st.integers(min_value=1, max_value=50))
def test_truncation_is_grapheme_safe(text: str, budget: int) -> None:
    truncated = truncate_to_tokens(text, budget)
    source_clusters = regex.findall(r"\X", text)
    kept = regex.findall(r"\X", truncated)
    assert kept == source_clusters[: len(kept)], "truncation must cut at cluster boundaries"


def test_family_emoji_never_split() -> None:
    text = "abc 👨‍👩‍👧‍👦" * 50
    truncated = truncate_to_tokens(text, budget=10)
    assert "‍" not in (truncated[-1],), "must not end mid-ZWJ-sequence"
    for cluster in regex.findall(r"\X", truncated):
        assert cluster in ("a", "b", "c", " ", "👨‍👩‍👧‍👦")


def test_dedup_drop_and_fold_are_deterministic() -> None:
    text = "keep\nkeep\nCookie policy notice\n\n\n\nspaced   out"
    once = fold_whitespace(drop_regex(dedup_lines(text), [r"(?i)cookie policy"]))
    twice = fold_whitespace(drop_regex(dedup_lines(text), [r"(?i)cookie policy"]))
    assert once == twice
    assert once.count("keep") == 1
    assert "Cookie" not in once
    assert "spaced out" in once
