"""Authenticated driver inbox, scoped entirely by the current account."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import literal, select, tuple_

from src.config import settings
from src.modules.driver_notifications.models import DriverNotification
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    CurrentActorDependency,
    DatabaseSession,
    authorize_request,
)
from src.modules.identity.policy_routing import PolicyRoute

router = APIRouter(
    prefix="/api/v1/driver/notifications",
    tags=["driver-notifications"],
    route_class=PolicyRoute,
    dependencies=[Depends(authorize_request)],
)


class Item(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: int
    event_type: str
    title: str
    message: str
    occurred_at: datetime
    created_at: datetime
    read_at: datetime | None


@router.get("")
@user_policy("driver.notification.read", "own", "driver")
async def inbox(
    db: DatabaseSession,
    actor: CurrentActorDependency,
    before: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    cutoff = datetime.now(UTC) - timedelta(
        days=settings.driver_notification_retention_days
    )
    stmt = select(DriverNotification).where(
        DriverNotification.driver_id == actor.user_id,
        DriverNotification.created_at >= cutoff,
    )
    if before:
        anchor = await db.scalar(
            select(DriverNotification).where(
                DriverNotification.id == before,
                DriverNotification.driver_id == actor.user_id,
            )
        )
        if anchor is None:
            raise HTTPException(404, "Không tìm thấy thông báo")
        stmt = stmt.where(
            tuple_(DriverNotification.created_at, DriverNotification.id)
            < tuple_(literal(anchor.created_at), literal(anchor.id))
        )
    rows = list(
        await db.scalars(
            stmt.order_by(
                DriverNotification.created_at.desc(), DriverNotification.id.desc()
            ).limit(limit + 1)
        )
    )
    return {
        "items": [Item.model_validate(row) for row in rows[:limit]],
        "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None,
    }


@router.post("/{notification_id}/read")
@user_policy("driver.notification.read", "own", "driver")
async def mark_read(
    notification_id: UUID, db: DatabaseSession, actor: CurrentActorDependency
) -> Item:
    row = await db.scalar(
        select(DriverNotification)
        .where(
            DriverNotification.id == notification_id,
            DriverNotification.driver_id == actor.user_id,
            DriverNotification.created_at
            >= datetime.now(UTC)
            - timedelta(days=settings.driver_notification_retention_days),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Không tìm thấy thông báo")
    row.read_at = row.read_at or datetime.now(UTC)
    await db.commit()
    return Item.model_validate(row)
