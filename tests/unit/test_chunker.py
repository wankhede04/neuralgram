"""Unit + property tests for the C2.1 chunker (M1-3 acceptance)."""

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from neuralgram.ingestion.canonicalize import CanonicalDoc, Provenance
from neuralgram.memory.chunker import chunk, estimate_tokens


def _doc(body: str) -> CanonicalDoc:
    return CanonicalDoc(
        body_md=body,
        provenance=Provenance(
            source_type="slack",
            source_id="C042MEMORY",
            external_id="1783296000.000100",
            author="U01ALICE",
            timestamp=datetime(2026, 7, 6, tzinfo=UTC),
        ),
        source_type="slack",
    )


@given(st.text(min_size=1, max_size=5000))
def test_identical_input_yields_identical_chunk_ids(body: str) -> None:
    first = [c.id for c in chunk(_doc(body), "tenant-a")]
    second = [c.id for c in chunk(_doc(body), "tenant-a")]
    assert first == second


@given(st.text(min_size=1, max_size=5000))
def test_reingest_creates_zero_new_ids(body: str) -> None:
    seen = {c.id for c in chunk(_doc(body), "tenant-a")}
    reingested = {c.id for c in chunk(_doc(body), "tenant-a")}
    assert reingested == seen


@given(st.text(min_size=20, max_size=2000).filter(lambda s: s.strip()))
def test_same_content_different_tenants_never_collides(body: str) -> None:
    ids_a = {c.id for c in chunk(_doc(body), "tenant-a")}
    ids_b = {c.id for c in chunk(_doc(body), "tenant-b")}
    assert not (ids_a & ids_b)


@given(st.text(max_size=20000))
def test_every_chunk_respects_token_budget(body: str) -> None:
    for draft in chunk(_doc(body), "tenant-a", max_tokens=100):
        assert draft.token_count <= 100


def test_multibyte_text_survives_chunking_intact() -> None:
    body = ("日本語テキスト🎉 " * 200).strip()
    drafts = chunk(_doc(body), "tenant-a", max_tokens=100)
    assert len(drafts) > 1
    reassembled = " ".join(d.content_md.replace("\n\n", " ") for d in drafts)
    assert reassembled.split() == body.split()


def test_chunks_carry_provenance_and_lifecycle() -> None:
    drafts = chunk(_doc("hello world"), "tenant-a")
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.provenance.author == "U01ALICE"
    assert draft.source_id == "C042MEMORY"
    assert draft.lifecycle == "pending_extraction"
    assert draft.id == draft.content_hash
    assert draft.token_count == estimate_tokens(draft.content_md)


def test_empty_body_yields_no_chunks() -> None:
    assert chunk(_doc("   \n\n  "), "tenant-a") == []
