"""Unit tests: compression calls record C8 metrics (M1-8 acceptance)."""

from prometheus_client import CollectorRegistry

from neuralgram.compression.engine import compress
from neuralgram.observability import metrics


def _counter_value(registry: CollectorRegistry, name: str, rule: str) -> float:
    value = registry.get_sample_value(f"{name}_total", {"rule": rule})
    return value or 0.0


def test_compress_records_token_and_reduction_metrics() -> None:
    before_in = _counter_value(metrics.registry, "neuralgram_compression_tokens_in", "builtin:text")
    before_out = _counter_value(
        metrics.registry, "neuralgram_compression_tokens_out", "builtin:text"
    )

    result = compress("dup line\ndup line\nunique line", budget=10_000)

    after_in = _counter_value(metrics.registry, "neuralgram_compression_tokens_in", "builtin:text")
    after_out = _counter_value(
        metrics.registry, "neuralgram_compression_tokens_out", "builtin:text"
    )
    assert after_in - before_in == result.in_tokens > 0
    assert after_out - before_out == result.out_tokens > 0
    assert result.out_tokens < result.in_tokens

    histogram_count = metrics.registry.get_sample_value(
        "neuralgram_compression_reduction_pct_count", {"rule": "builtin:text"}
    )
    assert histogram_count is not None and histogram_count >= 1
