from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import allow_roles
from src.modules.identity.dependencies import CurrentActorDependency, authorize_request
from src.modules.ocpp.models import RemoteCommandLog
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1", tags=["remote-logs"], dependencies=[Depends(authorize_request)]
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


class RemoteLogQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    charge_point_id: UUID | None = None
    user_id: UUID | None = None
    from_at: AwareDatetime | None = None
    to_at: AwareDatetime | None = None


class RemoteLogEntry(BaseModel):
    id: UUID
    user_id: UUID
    charge_point_id: UUID | None
    session_id: int | None
    command: str
    result: str
    created_at: datetime


@router.get("/remote-logs")
@allow_roles("admin", "operator")
async def get_remote_logs(
    query: Annotated[RemoteLogQuery, Query()],
    actor: CurrentActorDependency,
    session: Database,
) -> dict[str, object]:
    if query.from_at and query.to_at and query.from_at > query.to_at:
        raise HTTPException(422, "Thời gian bắt đầu phải trước thời gian kết thúc.")
    
    statement = select(RemoteCommandLog)
    
    if query.charge_point_id:
        statement = statement.where(RemoteCommandLog.charge_point_id == query.charge_point_id)
    if query.user_id:
        statement = statement.where(RemoteCommandLog.user_id == query.user_id)
    if query.from_at:
        statement = statement.where(RemoteCommandLog.created_at >= query.from_at)
    if query.to_at:
        statement = statement.where(RemoteCommandLog.created_at <= query.to_at)
        
    total = (
        await session.scalar(select(func.count()).select_from(statement.subquery()))
        or 0
    )
    
    rows = (
        await session.scalars(
            statement.order_by(RemoteCommandLog.created_at.desc(), RemoteCommandLog.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    
    items = [
        RemoteLogEntry(
            id=row.id,
            user_id=row.user_id,
            charge_point_id=row.charge_point_id,
            session_id=row.session_id,
            command=row.command,
            result=row.result,
            created_at=row.created_at,
        )
        for row in rows
    ]
    
    return {
        "items": items,
        "total": total,
        "page": query.page,
        "total_pages": max(1, (total + query.page_size - 1) // query.page_size),
    }
