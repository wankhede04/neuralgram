"""C1 canonicalizer: normalize raw source payloads into provenance-tagged Markdown.

Interface per spec §2: `ingest(source_id, raw_payload) -> [CanonicalDoc]`.
Normalizers are registered per source_type; Slack (export shape) is the
first supported source (ADR-0004).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from neuralgram.common.errors import UnsupportedSourceError


class Provenance(BaseModel):
    """The source trail attached to every canonical document."""

    source_type: str
    source_id: str
    external_id: str
    author: str
    timestamp: datetime
    url: str | None = None


class CanonicalDoc(BaseModel):
    """A normalized, provenance-tagged Markdown document ready for chunking (C2.1)."""

    body_md: str
    provenance: Provenance
    source_type: str


Normalizer = Callable[[str, dict[str, Any]], list[CanonicalDoc]]


def _slack_timestamp(ts: str) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=UTC)


def _normalize_slack(source_id: str, raw_payload: dict[str, Any]) -> list[CanonicalDoc]:
    """Normalize a Slack export payload (`{"messages": [...]}`) to one doc per message."""
    docs: list[CanonicalDoc] = []
    for message in raw_payload.get("messages", []):
        text = message.get("text", "")
        if not text.strip():
            continue
        ts = message["ts"]
        author = message.get("user") or message.get("username") or "unknown"
        provenance = Provenance(
            source_type="slack",
            source_id=source_id,
            external_id=ts,
            author=author,
            timestamp=_slack_timestamp(ts),
            url=message.get("permalink"),
        )
        header = (
            f"> source: slack {source_id} · author: {author} · "
            f"time: {provenance.timestamp.isoformat()} · id: {ts}"
        )
        docs.append(
            CanonicalDoc(
                body_md=f"{header}\n\n{text}",
                provenance=provenance,
                source_type="slack",
            )
        )
    return docs


_NORMALIZERS: dict[str, Normalizer] = {"slack": _normalize_slack}


def ingest(
    source_id: str, raw_payload: dict[str, Any], source_type: str = "slack"
) -> list[CanonicalDoc]:
    """Normalize `raw_payload` from `source_type` into canonical documents.

    Raises `UnsupportedSourceError` for source types without a registered
    normalizer. Pure function: no I/O, no persistence.
    """
    normalizer = _NORMALIZERS.get(source_type)
    if normalizer is None:
        raise UnsupportedSourceError(
            f"no normalizer registered for source_type={source_type!r}; "
            f"supported: {sorted(_NORMALIZERS)}"
        )
    return normalizer(source_id, raw_payload)
