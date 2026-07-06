"""Unit tests for C2.3 extraction verdicts (M2-4)."""

from neuralgram.memory.extraction import heuristic_verdict, parse_model_verdict


def test_heuristic_verdict_is_deterministic_and_bounded() -> None:
    content = "Deploy for Neuralgram lands Friday. Alice owns the migration checklist."
    first = heuristic_verdict(content)
    second = heuristic_verdict(content)
    assert first == second
    assert 0.0 <= first.score <= 1.0


def test_heuristic_scores_rich_content_above_trivial() -> None:
    rich = (
        "The Neuralgram memory service persists provenance-tagged chunks into Postgres "
        "with pgvector embeddings, gated by deterministic compression and routed via hints."
    )
    trivial = "ok ok ok ok"
    assert heuristic_verdict(rich).score > heuristic_verdict(trivial).score


def test_heuristic_extracts_entities_without_stopwords() -> None:
    verdict = heuristic_verdict("Please ask Alice Chen about Neuralgram before Friday.")
    names = {e["name"] for e in verdict.entities}
    assert "Alice Chen" in names
    assert "Neuralgram" in names
    assert "Please" not in names
    assert "Friday" not in names


def test_parse_model_verdict_accepts_valid_json() -> None:
    verdict = parse_model_verdict(
        '{"score": 0.8, "entities": [{"name": "Alice", "type": "person"}]}'
    )
    assert verdict is not None
    assert verdict.score == 0.8
    assert verdict.entities == [{"name": "Alice", "type": "person"}]


def test_parse_model_verdict_rejects_mock_and_garbage() -> None:
    assert parse_model_verdict("[mock:hint:fast:abc123]") is None
    assert parse_model_verdict('{"score": 7}') is None  # out of bounds
    assert parse_model_verdict("") is None
