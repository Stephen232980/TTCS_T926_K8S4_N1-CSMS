from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.alerts.service import alert_list, mutate_alert
from src.modules.identity.authorization import DataScope, user_policy
from src.modules.identity.dependencies import AuditEvidence, RequestScope
from src.modules.identity.policy_routing import PolicyRoute
from src.platform.database.session import get_db_session

Database = Annotated[AsyncSession, Depends(get_db_session)]


class CloseAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force: bool = Field(default=False, strict=True)
    reason: str = Field(default="", max_length=500)


def alert_router(area: str, role: str, scope_kind: DataScope) -> APIRouter:
    router = APIRouter(
        prefix=f"/api/v1/{area}/alerts",
        route_class=PolicyRoute,
        tags=["operational-alerts"],
    )

    @router.get("")
    @user_policy(f"{area}.alerts.read", scope_kind, role)
    async def read_alerts(
        db: Database,
        scope: RequestScope,
        status: Literal["active", "open", "acknowledged", "closed", "all"] = "active",
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> dict[str, object]:
        return await alert_list(db, scope, status, page)

    if area == "owner":
        return router

    @router.post("/{alert_id}/acknowledge")
    @user_policy(f"{area}.alerts.manage", "all", role)
    async def acknowledge(
        alert_id: UUID, db: Database, scope: RequestScope, evidence: AuditEvidence
    ) -> dict[str, str]:
        await mutate_alert(db, alert_id, "acknowledge", scope, evidence)
        return {"status": "acknowledged"}

    @router.post("/{alert_id}/close")
    @user_policy(f"{area}.alerts.manage", "all", role)
    async def close(
        alert_id: UUID,
        body: CloseAlert,
        db: Database,
        scope: RequestScope,
        evidence: AuditEvidence,
    ) -> dict[str, str]:
        await mutate_alert(
            db, alert_id, "close", scope, evidence, force=body.force, reason=body.reason
        )
        return {"status": "closed"}

    @router.post("/{alert_id}/retry-email")
    @user_policy(f"{area}.alerts.manage", "all", role)
    async def retry_email(
        alert_id: UUID, db: Database, scope: RequestScope, evidence: AuditEvidence
    ) -> dict[str, str]:
        await mutate_alert(db, alert_id, "retry-email", scope, evidence)
        return {"status": "queued"}

    return router


ops_router = alert_router("ops", "operator", "all")
owner_router = alert_router("owner", "station_owner", "owned")
admin_router = alert_router("admin", "admin", "all")
