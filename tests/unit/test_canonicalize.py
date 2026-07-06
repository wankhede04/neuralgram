"""Unit tests for the C1 canonicalizer (M1-2 acceptance)."""

import json
from pathlib import Path

import pytest

from neuralgram.common.errors import UnsupportedSourceError
from neuralgram.ingestion.canonicalize import ingest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "slack_export_sample.json"


def _sample_payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())  # type: ignore[no-any-return]


def test_markdown_carries_full_provenance() -> None:
    docs = ingest("C042MEMORY", _sample_payload())
    first = docs[0]

    assert first.provenance.source_type == "slack"
    assert first.provenance.source_id == "C042MEMORY"
    assert first.provenance.author == "U01ALICE"
    assert first.provenance.external_id == "1783296000.000100"
    assert first.provenance.timestamp.isoformat() == "2026-07-06T00:00:00.000100+00:00"
    assert first.provenance.url and first.provenance.url.startswith("https://example.slack.com")

    for token in ("slack", "C042MEMORY", "U01ALICE", "1783296000.000100", "2026-07-06"):
        assert token in first.body_md, f"body_md must carry provenance token {token!r}"
    assert "migration checklist" in first.body_md


def test_empty_messages_are_skipped_and_multibyte_preserved() -> None:
    docs = ingest("C042MEMORY", _sample_payload())
    assert len(docs) == 2
    assert "日本語のテキストも問題なく扱えます 🎉" in docs[1].body_md


def test_unknown_source_type_is_rejected() -> None:
    with pytest.raises(UnsupportedSourceError, match="no normalizer"):
        ingest("C042MEMORY", _sample_payload(), source_type="carrier-pigeon")
