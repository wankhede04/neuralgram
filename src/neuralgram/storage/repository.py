"""Repository base enforcing tenant scoping on every query (standards §8, C7).

Tenant-scoped tables must be queried through a `TenantScopedRepository`
subclass; the tenant filter is applied structurally, so an un-scoped query
cannot be expressed through the repository API.
"""

from typing import Generic, TypeVar

from sqlalchemy import Select, select

from neuralgram.common.errors import MissingTenantScopeError
from neuralgram.storage.models import Base

ModelT = TypeVar("ModelT", bound=Base)


class TenantScopedRepository(Generic[ModelT]):
    """Base class for repositories over tables that carry `tenant_id`.

    Subclasses set `model`. Instantiation fails without a non-empty
    tenant_id or when the model lacks a `tenant_id` column; every select
    built by `scoped_select` carries the tenant filter.
    """

    model: type[ModelT]

    def __init__(self, tenant_id: str) -> None:
        if not tenant_id or not tenant_id.strip():
            raise MissingTenantScopeError(f"{type(self).__name__} requires a non-empty tenant_id")
        if not hasattr(self.model, "tenant_id"):
            raise MissingTenantScopeError(
                f"{self.model.__name__} has no tenant_id column; "
                "tenant-scoped repositories only work on tenant-scoped tables"
            )
        self.tenant_id = tenant_id

    def scoped_select(self) -> Select[tuple[ModelT]]:
        """Return a SELECT over `model` filtered to this repository's tenant."""
        return select(self.model).where(self.model.tenant_id == self.tenant_id)  # type: ignore[attr-defined]
