"""One-query scoped snapshots and reconnectable server-sent monitoring events."""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import (
    CurrentActor,
    allow_roles,
    build_actor_scope,
)
from src.modules.identity.dependencies import CurrentActorDependency, authorize_request
from src.modules.identity.repository import IdentityRepository
from src.modules.identity.security import hash_session_token
from src.modules.ocpp.connection_registry import ocpp_connections
from src.modules.stations.models import ChargePoint, Connector, ConnectorError, Station
from src.platform.database.session import SessionFactory, get_db_session

router = APIRouter(
    prefix="/api/v1/ocpp/connections",
    tags=["OCPP monitoring"],
    dependencies=[Depends(authorize_request)],
)


class MonitorQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class ConnectorResponse(BaseModel):
    id: UUID
    number: int
    status: str
    raw_ocpp_status: str | None
    status_updated_at: datetime
    last_error_code: str | None
    last_vendor_error_code: str | None
    last_error_at: datetime | None


class ConnectionResponse(BaseModel):
    id: UUID
    code: str
    station_name: str
    connected: bool
    boot_accepted: bool
    connected_at: datetime | None
    last_boot_at: datetime | None
    last_seen_at: datetime | None
    online: bool
    heartbeat_interval_seconds: int
    raw_ocpp_status: str | None
    error_code: str | None
    vendor_error_code: str | None
    error_at: datetime | None
    vendor: str | None
    model: str | None
    firmware_version: str | None
    connectors: list[ConnectorResponse]


class MonitorResponse(BaseModel):
    items: list[ConnectionResponse]
    total: int
    page: int
    total_pages: int


async def monitoring_snapshot(
    session: AsyncSession,
    actor: CurrentActor,
    query: MonitorQuery,
    now: datetime | None = None,
) -> MonitorResponse:
    now = now or datetime.now(UTC)
    latest_errors = select(
        ConnectorError.connector_id,
        ConnectorError.error_code,
        ConnectorError.vendor_error_code,
        ConnectorError.occurred_at,
        func.row_number()
        .over(
            partition_by=ConnectorError.connector_id,
            order_by=(ConnectorError.occurred_at.desc(), ConnectorError.id.desc()),
        )
        .label("position"),
    ).subquery()
    statement = (
        select(
            ChargePoint,
            Station.name,
            Station.status,
            Connector,
            latest_errors.c.error_code,
            latest_errors.c.vendor_error_code,
            latest_errors.c.occurred_at,
        )
        .join(Station, Station.id == ChargePoint.station_id)
        .outerjoin(
            Connector,
            and_(
                Connector.charge_point_id == ChargePoint.id,
                Connector.archived_at.is_(None),
            ),
        )
        .outerjoin(
            latest_errors,
            and_(
                latest_errors.c.connector_id == Connector.id,
                latest_errors.c.position == 1,
            ),
        )
        .where(ChargePoint.archived_at.is_(None), Station.archived_at.is_(None))
    )
    scope = build_actor_scope(actor)
    if scope.owner_id is not None:
        statement = statement.where(Station.owner_id == scope.owner_id)
    rows = (
        await session.execute(
            statement.execution_options(populate_existing=True).order_by(
                Station.name,
                ChargePoint.code,
                ChargePoint.id,
                Connector.connector_number,
            )
        )
    ).all()
    connections = await ocpp_connections.snapshot()
    grouped: dict[UUID, ConnectionResponse] = {}
    for (
        charger,
        station_name,
        station_status,
        connector,
        error,
        vendor_error,
        error_at,
    ) in rows:
        if charger.id not in grouped:
            connection = connections.get(charger.id)
            online = (
                station_status != "blocked"
                and charger.last_boot_at is not None
                and (connection is None or connection.boot_accepted)
                and charger.last_seen_at is not None
                and now - charger.last_seen_at
                <= timedelta(seconds=2 * charger.heartbeat_interval_seconds)
            )
            grouped[charger.id] = ConnectionResponse(
                id=charger.id,
                code=charger.code,
                station_name=station_name,
                connected=connection is not None,
                boot_accepted=connection.boot_accepted if connection else False,
                connected_at=connection.connected_at if connection else None,
                last_boot_at=charger.last_boot_at,
                last_seen_at=charger.last_seen_at,
                online=online,
                heartbeat_interval_seconds=charger.heartbeat_interval_seconds,
                raw_ocpp_status=charger.raw_ocpp_status if online else None,
                error_code=charger.error_code,
                vendor_error_code=charger.vendor_error_code,
                error_at=charger.error_at,
                vendor=charger.vendor,
                model=charger.model,
                firmware_version=charger.firmware_version,
                connectors=[],
            )
        item = grouped[charger.id]
        if connector is not None:
            item.connectors.append(
                ConnectorResponse(
                    id=connector.id,
                    number=connector.connector_number,
                    status=connector.status if item.online else "unknown",
                    raw_ocpp_status=connector.raw_ocpp_status if item.online else None,
                    status_updated_at=connector.status_updated_at,
                    last_error_code=error,
                    last_vendor_error_code=vendor_error,
                    last_error_at=error_at,
                )
            )
    items = list(grouped.values())
    total = len(items)
    start = (query.page - 1) * query.page_size
    return MonitorResponse(
        items=items[start : start + query.page_size],
        total=total,
        page=query.page,
        total_pages=(total + query.page_size - 1) // query.page_size,
    )


@router.get("", response_model=MonitorResponse)
@allow_roles("station_owner", "operator", "admin")
async def list_connections(
    query: Annotated[MonitorQuery, Query()],
    actor: CurrentActorDependency,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MonitorResponse:
    return await monitoring_snapshot(session, actor, query)


async def monitoring_events(
    request: Request, actor: CurrentActor, query: MonitorQuery
) -> AsyncIterator[str]:
    token = request.cookies.get("session")
    while not await request.is_disconnected():
        try:
            async with SessionFactory() as session:
                # Revalidate session/roles each snapshot; logout and permission changes stop the stream.
                current = await IdentityRepository(
                    session
                ).get_current_actor_by_session_hash(
                    hash_session_token(token or ""), datetime.now(UTC)
                )
                if current is None or not current.roles.intersection(
                    {"station_owner", "operator", "admin"}
                ):
                    yield "event: access-denied\ndata: {}\n\n"
                    return
                snapshot = await monitoring_snapshot(session, current, query)
            yield f"retry: 1000\ndata: {snapshot.model_dump_json()}\n\n"
        except SQLAlchemyError:
            logging.getLogger("csms.ocpp").error("ocpp_monitor_stream_failed")
            return
        await asyncio.sleep(0.5)


@router.get("/events")
@allow_roles("station_owner", "operator", "admin")
async def stream_connections(
    request: Request,
    query: Annotated[MonitorQuery, Query()],
    actor: CurrentActorDependency,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    # Release the authentication transaction before starting a long-lived response.
    await session.commit()
    return StreamingResponse(
        monitoring_events(request, actor, query),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
