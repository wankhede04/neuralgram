"""Async database engine and session factories (standards §1: SQLAlchemy 2.x async).

RLS plumbing (M5-1): worker/system code paths run with the
`neuralgram.context='system'` GUC (full visibility, trusted code only);
API read paths run with `neuralgram.tenant_id` so Postgres row-level
security fail-closes anything the repository layer might miss.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.orm import SessionTransaction

from neuralgram.common.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    """Create the async engine for `settings.database_url`. No connection is opened yet."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to `engine` (expire_on_commit disabled for async use)."""
    return async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(SyncSession, "after_begin")
def _set_system_rls_context(
    session: SyncSession, transaction: SessionTransaction, connection: Connection
) -> None:
    """Open every transaction of system-flagged sessions with the system RLS GUC."""
    if session.info.get("neuralgram_system"):
        connection.execute(text("SET LOCAL neuralgram.context = 'system'"))


def build_system_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory whose transactions carry the system RLS context.

    Trusted worker/system code sees all tenants' rows. Never hand these
    sessions to request-scoped read paths.
    """
    return async_sessionmaker(engine, expire_on_commit=False, info={"neuralgram_system": True})


@asynccontextmanager
async def tenant_session(
    factory: async_sessionmaker[AsyncSession], tenant_id: str
) -> AsyncIterator[AsyncSession]:
    """Yield a session whose transaction carries the tenant's RLS context.

    The GUC is transaction-local (`is_local=true`), so it must be re-set
    after any commit; request read paths use a single transaction.
    """
    async with factory() as session:
        await session.execute(
            text("SELECT set_config('neuralgram.tenant_id', :tenant, true)"),
            {"tenant": tenant_id},
        )
        yield session


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a session inside a transaction: commit on success, rollback on error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
