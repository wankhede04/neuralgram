"""C2.5 tree-scoped retrieval: drill_down / topic / global (M3-4).

Every returned node carries its `child_ids`, which chain down to source
chunks — the provenance guarantee holds at every scope.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession

from neuralgram.storage.models import Summary
from neuralgram.storage.repository import TenantScopedRepository


class SummaryNode(BaseModel):
    """A summary-tree node with its provenance chain (child ids)."""

    summary_id: str
    tree_type: str
    scope_id: str
    level: int
    body_md: str
    child_ids: dict[str, Any]
    sealed_at: str | None


def _to_node(row: Summary) -> SummaryNode:
    return SummaryNode(
        summary_id=row.id,
        tree_type=row.tree_type,
        scope_id=row.scope_id,
        level=row.level,
        body_md=row.body_md,
        child_ids=row.child_ids,
        sealed_at=row.sealed_at.isoformat() if row.sealed_at else None,
    )


class TreeRetrieval(TenantScopedRepository[Summary]):
    """Tenant-scoped retrieval over summary trees."""

    model = Summary

    async def drill_down(
        self, session: AsyncSession, source_id: str, level: int | None = None
    ) -> list[SummaryNode]:
        """Source-tree nodes for `source_id`, highest level first (root -> leaves)."""
        statement = self.scoped_select().where(
            Summary.tree_type == "source", Summary.scope_id == source_id
        )
        if level is not None:
            statement = statement.where(Summary.level == level)
        statement = statement.order_by(desc(Summary.level), Summary.id)
        rows = (await session.execute(statement)).scalars().all()
        return [_to_node(row) for row in rows]

    async def topic(self, session: AsyncSession, entity_id: str) -> list[SummaryNode]:
        """Topic-tree nodes for a (hot) entity; empty when never materialized."""
        statement = (
            self.scoped_select()
            .where(Summary.tree_type == "topic", Summary.scope_id == entity_id)
            .order_by(desc(Summary.level), Summary.id)
        )
        rows = (await session.execute(statement)).scalars().all()
        return [_to_node(row) for row in rows]

    async def global_digest(self, session: AsyncSession, day: date) -> SummaryNode | None:
        """The global digest node for `day`, or None when no digest exists."""
        statement = self.scoped_select().where(
            Summary.tree_type == "global", Summary.scope_id == str(day)
        )
        row = (await session.execute(statement)).scalar_one_or_none()
        return _to_node(row) if row is not None else None
