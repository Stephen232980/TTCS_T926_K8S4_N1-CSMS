from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import allow_roles
from src.modules.identity.dependencies import CurrentActorDependency, authorize_request
from src.modules.ocpp.control import command_status, execute_command
from src.modules.ocpp.control_models import ControlRequest, ControlResult
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/ocpp", tags=["control"], dependencies=[Depends(authorize_request)]
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


class CommandBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class ResetBody(CommandBody):
    type: Literal["Soft", "Hard"] = "Soft"


class AuditQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    charge_point_code: str | None = Field(default=None, max_length=64)
    actor_email: str | None = Field(default=None, max_length=320)
    from_at: AwareDatetime | None = None
    to_at: AwareDatetime | None = None


class AuditEntry(BaseModel):
    id: UUID
    actor: str
    charge_point_code: str
    transaction_id: int | None
    action: str
    payload: dict[str, object]
    created_at: datetime
    status: str
    received_at: datetime | None


@router.post("/charge-points/{charger_id}/reset")
@allow_roles("operator", "admin")
async def reset(
    charger_id: UUID, body: ResetBody, actor: CurrentActorDependency, session: Database
) -> dict[str, object]:
    await session.commit()  # Release the authentication connection before waiting.
    return await execute_command(
        actor.user_id, body.request_id, "Reset", charger_id, body.type
    )


@router.post("/sessions/{transaction_id}/stop")
@allow_roles("operator", "admin")
async def remote_stop(
    transaction_id: int,
    body: CommandBody,
    actor: CurrentActorDependency,
    session: Database,
) -> dict[str, object]:
    await session.commit()
    return await execute_command(
        actor.user_id, body.request_id, "RemoteStopTransaction", transaction_id
    )


@router.get("/commands/{command_id}")
@allow_roles("operator", "admin")
async def get_command(
    command_id: UUID, actor: CurrentActorDependency, session: Database
) -> dict[str, object]:
    command = await session.get(ControlRequest, command_id)
    if command is None or (
        command.actor_id != actor.user_id and "admin" not in actor.roles
    ):
        raise HTTPException(404, "Không tìm thấy yêu cầu.")
    return {"id": command.id, "status": await command_status(session, command.id)}


@router.get("/control-audit")
@allow_roles("admin")
async def audit(
    query: Annotated[AuditQuery, Query()],
    actor: CurrentActorDependency,
    session: Database,
) -> dict[str, object]:
    if query.from_at and query.to_at and query.from_at > query.to_at:
        raise HTTPException(422, "Thời gian bắt đầu phải trước thời gian kết thúc.")
    statement = select(
        ControlRequest,
        ControlRequest.actor_email,
        ControlRequest.charge_point_code,
        ControlResult.status,
        ControlResult.received_at,
    ).outerjoin(ControlResult)
    if query.charge_point_code:
        statement = statement.where(
            func.lower(ControlRequest.charge_point_code)
            == query.charge_point_code.strip().lower()
        )
    if query.actor_email:
        statement = statement.where(
            func.lower(ControlRequest.actor_email) == query.actor_email.strip().lower()
        )
    if query.from_at:
        statement = statement.where(ControlRequest.created_at >= query.from_at)
    if query.to_at:
        statement = statement.where(ControlRequest.created_at <= query.to_at)
    total = (
        await session.scalar(select(func.count()).select_from(statement.subquery()))
        or 0
    )
    rows = (
        await session.execute(
            statement.order_by(ControlRequest.created_at.desc(), ControlRequest.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    items = [
        AuditEntry(
            id=row[0].id,
            actor=row[1],
            charge_point_code=row[2],
            transaction_id=row[0].transaction_id,
            action=row[0].action,
            payload=row[0].payload,
            created_at=row[0].created_at,
            status=row[3] or "Pending",
            received_at=row[4],
        )
        for row in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": query.page,
        "total_pages": max(1, (total + query.page_size - 1) // query.page_size),
    }
