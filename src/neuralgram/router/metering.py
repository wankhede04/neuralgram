"""C4 per-tenant usage metering and hard spend caps (M4-3).

Every gateway call with a tenant is (1) pre-checked against the tenant's
hard cap and (2) recorded durably to `usage_events` plus Prometheus
counters. Mock models carry nominal prices so the cost math is exercised
end to end; real provider prices join the table when providers do (M4-2).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.common.errors import NeuralgramError
from neuralgram.observability import metrics
from neuralgram.storage.models import UsageEvent, User

_LOCK_WAIT_TIMEOUT_MS = 3_000

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


class SignupCallLimitExceededError(NeuralgramError):
    """A self-serve signup tenant reached its lifetime call limit for this call category."""


class TooManyConcurrentRequestsError(NeuralgramError):
    """A tenant has too many in-flight metered calls; new ones fail fast instead of queueing."""


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
        signup_call_limit: int = 3,
        demo_tenant_prefix: str | None = None,
        demo_spend_cap_usd: float = 0.0,
    ) -> None:
        self._session_factory = session_factory
        self._caps = {tenant: Decimal(str(cap)) for tenant, cap in spend_caps_usd.items()}
        self._signup_call_limit = signup_call_limit
        self._demo_tenant_prefix = demo_tenant_prefix or None
        self._demo_spend_cap = Decimal(str(demo_spend_cap_usd)) if demo_spend_cap_usd else None

    @asynccontextmanager
    async def tenant_lock(self, tenant_id: str) -> AsyncIterator[None]:
        """Serialize metered calls for one tenant (session-level Postgres advisory lock).

        `check_cap`/`check_signup_call_limit` are check-then-act against
        `usage_events` -- without this, concurrent calls for the same tenant
        can all pass the check before any of them is recorded, blowing past
        the cap. Holding this lock across check -> provider call -> record
        closes that race; unrelated tenants are never blocked by it.
        """
        async with self._session_factory() as session:
            # A caller stacking many concurrent requests against its own tenant
            # would otherwise queue on the blocking lock while holding a pooled
            # DB connection open -- bounding the wait keeps that from starving
            # the connection pool for unrelated tenants (a self-inflicted DoS).
            await session.execute(text(f"SET LOCAL lock_timeout = '{_LOCK_WAIT_TIMEOUT_MS}ms'"))
            try:
                await session.execute(
                    text("SELECT pg_advisory_lock(hashtext(:tid))"), {"tid": tenant_id}
                )
            except DBAPIError as exc:
                raise TooManyConcurrentRequestsError(
                    "Too many simultaneous requests on this account right now. "
                    "Please retry in a moment."
                ) from exc
            try:
                yield
            finally:
                await session.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:tid))"), {"tid": tenant_id}
                )

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

    async def spent_usd_by_prefix(self, tenant_prefix: str) -> Decimal:
        """Total recorded spend across every tenant_id starting with `tenant_prefix`.

        Used for the demo tenant family: each visitor gets its own per-IP
        tenant_id (`{demo_tenant_id}-{ip_fingerprint}`), so an exact-match
        cap can never catch them collectively -- this aggregates spend
        across all of them under one shared ceiling.
        """
        async with self._session_factory() as session:
            total = (
                await session.execute(
                    select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
                        UsageEvent.tenant_id.like(f"{tenant_prefix}%")
                    )
                )
            ).scalar_one()
        return Decimal(total)

    async def check_cap(self, tenant_id: str) -> None:
        """Raise `SpendCapExceededError` when the tenant (or its demo family) hit its cap."""
        demo_prefix = self._demo_tenant_prefix
        if demo_prefix is not None and self._demo_spend_cap is not None:
            is_demo_family = tenant_id == demo_prefix or tenant_id.startswith(f"{demo_prefix}-")
            if is_demo_family:
                demo_spent = await self.spent_usd_by_prefix(demo_prefix)
                if demo_spent >= self._demo_spend_cap:
                    raise SpendCapExceededError(
                        "The demo has reached its shared usage budget for today. "
                        "Sign up for your own tenant to keep going, or try again later."
                    )

        cap = self._caps.get(tenant_id)
        if cap is None:
            return
        spent = await self.spent_usd(tenant_id)
        if spent >= cap:
            raise SpendCapExceededError(
                f"tenant {tenant_id!r} reached its spend cap "
                f"(spent ${spent:.6f} of ${cap:.2f}); further model calls are blocked"
            )

    async def check_signup_call_limit(self, tenant_id: str, hint: str | None) -> None:
        """Raise `SignupCallLimitExceededError` if a signup tenant hit its lifetime cap.

        Only applies to tenants with a matching `users` row (self-serve
        signups) -- static .env keys and the demo tenant have no such
        row and are never affected. Completion calls (any hint except
        "embed") and embed calls are counted and capped independently.
        """
        async with self._session_factory() as session:
            is_signup_tenant = (
                await session.execute(select(User.id).where(User.tenant_id == tenant_id))
            ).scalar_one_or_none() is not None
            if not is_signup_tenant:
                return

            is_embed = hint == "embed"
            filter_clause = (
                UsageEvent.hint == "embed"
                if is_embed
                else or_(UsageEvent.hint != "embed", UsageEvent.hint.is_(None))
            )
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(UsageEvent)
                    .where(UsageEvent.tenant_id == tenant_id, filter_clause)
                )
            ).scalar_one()

        if count >= self._signup_call_limit:
            if is_embed:
                message = (
                    f"You've used all {self._signup_call_limit} free searches/ingests on "
                    "this account. Sign up for your own tenant with no limits, or contact "
                    "us for more."
                )
            else:
                message = (
                    f"This account has used all {self._signup_call_limit} free AI-processing "
                    "calls. Further automatic processing (summaries, extraction) is paused."
                )
            raise SignupCallLimitExceededError(message)

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
