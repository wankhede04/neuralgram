"""Unit tests: tenant scoping is enforced by the repository base (P0-5 acceptance)."""

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from neuralgram.common.errors import MissingTenantScopeError
from neuralgram.storage.models import Base
from neuralgram.storage.repository import TenantScopedRepository


class _ScopedThing(Base):
    __tablename__ = "_test_scoped_thing"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(index=True)


class _UnscopedThing(Base):
    __tablename__ = "_test_unscoped_thing"

    id: Mapped[int] = mapped_column(primary_key=True)


class _ScopedRepo(TenantScopedRepository[_ScopedThing]):
    model = _ScopedThing


class _UnscopedRepo(TenantScopedRepository[_UnscopedThing]):
    model = _UnscopedThing


def test_empty_tenant_id_is_rejected() -> None:
    with pytest.raises(MissingTenantScopeError):
        _ScopedRepo("")
    with pytest.raises(MissingTenantScopeError):
        _ScopedRepo("   ")


def test_model_without_tenant_column_is_rejected() -> None:
    with pytest.raises(MissingTenantScopeError, match="no tenant_id column"):
        _UnscopedRepo("tenant-a")


def test_every_select_carries_the_tenant_filter() -> None:
    repo = _ScopedRepo("tenant-a")
    sql = str(repo.scoped_select().compile())
    assert "tenant_id" in sql
    assert "WHERE" in sql
