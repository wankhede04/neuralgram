"""C4 per-tenant usage metering and hard spend caps (M4-3).

Every gateway call with a tenant is (1) pre-checked against the tenant's
hard cap and (2) recorded durably to `usage_events` plus Prometheus
counters. Mock models carry nominal prices so the cost math is exercised
end to end; real provider prices join the table when providers do (M4-2).
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.common.errors import NeuralgramError
from neuralgram.observability import metrics
from neuralgram.storage.models import UsageEvent

# USD per 1M tokens: (input, output). Nominal prices for mock models.
PRICE_TABLE: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
    ("mock", "mock-reasoning"): (Decimal("15.00"), Decimal("75.00")),
    ("mock", "mock-fast"): (Decimal("1.00"), Decimal("5.00")),
    ("mock", "mock-vision"): (Decimal("3.00"), Decimal("15.00")),
    ("mock", "mock-summarize"): (Decimal("1.00"), Decimal("5.00")),
    ("mock", "mock-code"): (Decimal("3.00"), Decimal("15.00")),
    ("mock", "mock-embed"): (Decimal("0.10"), Decimal("0.00")),
}
_DEFAULT_PRICE = (Decimal("3.00"), Decimal("15.00"))
_MILLION = Decimal(1_000_000)


class SpendCapExceededError(NeuralgramError):
    """The tenant's hard spend cap is reached; the model call was blocked."""


def call_cost_usd(provider: str, model: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Cost of one call from the price table (default price for unknown models)."""
    price_in, price_out = PRICE_TABLE.get((provider, model), _DEFAULT_PRICE)
    return (tokens_in * price_in + tokens_out * price_out) / _MILLION


class UsageMeter:
    """Durable per-tenant accounting with hard caps."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        spend_caps_usd: dict[str, float],
    ) -> None:
        self._session_factory = session_factory
        self._caps = {tenant: Decimal(str(cap)) for tenant, cap in spend_caps_usd.items()}

    async def spent_usd(self, tenant_id: str) -> Decimal:
        """Total recorded spend for a tenant."""
        async with self._session_factory() as session:
            total = (
                await session.execute(
                    select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
                        UsageEvent.tenant_id == tenant_id
                    )
                )
            ).scalar_one()
        return Decimal(total)

    async def check_cap(self, tenant_id: str) -> None:
        """Raise `SpendCapExceededError` when the tenant has reached its hard cap."""
        cap = self._caps.get(tenant_id)
        if cap is None:
            return
        spent = await self.spent_usd(tenant_id)
        if spent >= cap:
            raise SpendCapExceededError(
                f"tenant {tenant_id!r} reached its spend cap "
                f"(spent ${spent:.6f} of ${cap:.2f}); further model calls are blocked"
            )

    async def record(
        self,
        tenant_id: str,
        provider: str,
        model: str,
        hint: str | None,
        tokens_in: int,
        tokens_out: int,
    ) -> Decimal:
        """Persist one usage event and update Prometheus counters; returns the call cost."""
        cost = call_cost_usd(provider, model, tokens_in, tokens_out)
        async with self._session_factory() as session:
            session.add(
                UsageEvent(
                    id=uuid.uuid4().hex,
                    tenant_id=tenant_id,
                    provider=provider,
                    model=model,
                    hint=hint,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost,
                )
            )
            await session.commit()
        label_hint = hint or "none"
        metrics.model_tokens_total.labels(tenant_id, label_hint, "in").inc(tokens_in)
        metrics.model_tokens_total.labels(tenant_id, label_hint, "out").inc(tokens_out)
        metrics.model_cost_usd_total.labels(tenant_id, label_hint).inc(float(cost))
        return cost
