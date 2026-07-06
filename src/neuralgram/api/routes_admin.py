"""Admin routes (C7): audit-trail queries and GDPR erasure — admin role only,
always scoped to the caller's own tenant."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, select

from neuralgram.api.deps import require_role
from neuralgram.common.db import tenant_session
from neuralgram.memory.erasure import ErasureReport, ErasureService
from neuralgram.storage.models import AuditEvent

router = APIRouter(prefix="/admin", tags=["admin"])

AdminTenant = Annotated[str, Depends(require_role("admin"))]


class AuditRecord(BaseModel):
    """One audit-trail entry."""

    actor: str
    action: str
    resource: str
    status: int
    created_at: str


@router.get("/audit", response_model=list[AuditRecord])
async def audit_endpoint(
    tenant_id: AdminTenant,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditRecord]:
    """The tenant's audit trail (who queried whose memory), newest first."""
    factory = request.app.state.session_factory
    async with tenant_session(factory, tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(AuditEvent)
                    .where(AuditEvent.tenant_id == tenant_id)
                    .order_by(desc(AuditEvent.created_at))
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return [
        AuditRecord(
            actor=row.actor,
            action=row.action,
            resource=row.resource,
            status=row.status,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.post("/erase", response_model=ErasureReport)
async def erase_endpoint(tenant_id: AdminTenant, request: Request) -> ErasureReport:
    """GDPR erasure of the caller's own tenant: cascade delete of all memory.

    Irreversible. Usage and audit records are retained (billing/security).
    """
    service = ErasureService(
        request.app.state.system_session_factory,
        Path(request.app.state.settings.vault_path),
    )
    return await service.erase_tenant(tenant_id)
