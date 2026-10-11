from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.models import (
    ChargingCard,
    ChargingSession,
    ChargingSessionEvent,
    MeterSample,
    PendingChargingMessage,
)
from src.modules.charging.recovery import manual_close
from src.modules.charging.service import tag_hash
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    AuditEvidence,
    CurrentActorDependency,
    RequestScope,
    authorize_request,
)
from src.modules.identity.models import Role, User, UserRole
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/charging",
    tags=["charging"],
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


class CardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_tag: str = Field(min_length=1, max_length=20)
    driver_email: str = Field(max_length=320)
    expires_at: AwareDatetime | None = None


class CardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "blocked"]


class CardResponse(BaseModel):
    id: UUID
    tag_tail: str
    driver_email: str
    status: str
    expires_at: datetime | None


class SessionQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    state: Literal["all", "open", "closed", "review", "abnormal"] = "all"


class SessionResponse(BaseModel):
    id: int
    station_name: str
    charge_point_code: str
    connector_number: int
    tag_tail: str
    authorization_status: str
    started_at: datetime
    ended_at: datetime | None
    meter_start_wh: Decimal
    meter_stop_wh: Decimal | None
    energy_kwh: Decimal | None
    latest_meter_wh: Decimal | None
    latest_meter_at: datetime | None
    stop_reason: str | None
    review_reasons: list[str]
    abnormal_since: datetime | None
    recovery_at: datetime | None
    manual_closed_at: datetime | None
    manual_close_reason: str | None
    closed_by: UUID | None


class ManualCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class SampleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    timestamp: datetime
    measurand: str
    phase: str
    location: str
    value: Decimal = Field(
        description="Canonical sample value; energy counters are Wh, not kWh."
    )
    unit: str = Field(
        description="Canonical unit stored at ingestion; do not convert again on read."
    )


class SessionPage(BaseModel):
    items: list[SessionResponse]
    total: int
    page: int
    total_pages: int


class SamplePage(BaseModel):
    items: list[SampleResponse]
    total: int
    page: int
    total_pages: int


@router.get("/cards", response_model=list[CardResponse])
@user_policy("owner.charging.cards", "owned", "station_owner")
async def cards(
    actor: CurrentActorDependency, scope: RequestScope, session: Database
) -> list[CardResponse]:
    query = select(ChargingCard, User.email).join(
        User, User.id == ChargingCard.driver_id
    )
    owner = scope.owner_id
    if owner is not None:
        query = query.where(ChargingCard.issuer_id == owner)
    rows = (
        await session.execute(query.order_by(ChargingCard.created_at.desc()).limit(100))
    ).all()
    return [
        CardResponse(
            id=card.id,
            tag_tail=card.tag_tail,
            driver_email=email,
            status=card.status,
            expires_at=card.expires_at,
        )
        for card, email in rows
    ]


@router.post("/cards", response_model=CardResponse, status_code=201)
@user_policy("owner.charging.create_card", "owned", "station_owner")
async def create_card(
    body: CardCreate,
    actor: CurrentActorDependency,
    scope: RequestScope,
    session: Database,
) -> CardResponse:
    driver = await session.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            User.email == body.driver_email.strip().lower(),
            User.status == "active",
            Role.code == "driver",
        )
    )
    if driver is None:
        raise HTTPException(422, "Không tìm thấy tài xế đang hoạt động với email này.")
    card = ChargingCard(
        tag_hash=tag_hash(body.id_tag),
        tag_tail=body.id_tag[-4:],
        driver_id=driver.id,
        issuer_id=actor.user_id,
        expires_at=body.expires_at,
    )
    session.add(card)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Thẻ đã được khai báo.") from None
    return CardResponse(
        id=card.id,
        tag_tail=card.tag_tail,
        driver_email=driver.email,
        status=card.status,
        expires_at=card.expires_at,
    )


@router.patch("/cards/{card_id}", response_model=CardResponse)
@user_policy("owner.charging.update_card", "owned", "station_owner")
async def update_card(
    card_id: UUID,
    body: CardUpdate,
    actor: CurrentActorDependency,
    scope: RequestScope,
    session: Database,
) -> CardResponse:
    query = (
        select(ChargingCard, User.email)
        .join(User, User.id == ChargingCard.driver_id)
        .where(ChargingCard.id == card_id)
    )
    owner = scope.owner_id
    if owner is not None:
        query = query.where(ChargingCard.issuer_id == owner)
    row = (await session.execute(query.with_for_update(of=ChargingCard))).first()
    if row is None:
        raise HTTPException(404, "Không tìm thấy thẻ trong phạm vi quản lý.")
    card, email = row
    card.status = body.status
    await session.flush()
    return CardResponse(
        id=card.id,
        tag_tail=card.tag_tail,
        driver_email=email,
        status=card.status,
        expires_at=card.expires_at,
    )


def session_row(
    transaction: ChargingSession,
    name: str,
    code: str,
    number: int,
    meter: Decimal | None,
    timestamp: datetime | None,
) -> SessionResponse:
    return SessionResponse(
        id=transaction.id,
        station_name=name,
        charge_point_code=code,
        connector_number=number,
        tag_tail=transaction.tag_tail,
        authorization_status=transaction.authorization_status,
        started_at=transaction.started_at,
        ended_at=transaction.ended_at,
        meter_start_wh=transaction.meter_start_wh,
        meter_stop_wh=transaction.meter_stop_wh,
        energy_kwh=transaction.energy_kwh,
        latest_meter_wh=meter,
        latest_meter_at=timestamp,
        stop_reason=transaction.stop_reason,
        review_reasons=transaction.review_reasons,
        abnormal_since=transaction.abnormal_since,
        recovery_at=transaction.recovery_at,
        manual_closed_at=transaction.manual_closed_at,
        manual_close_reason=transaction.manual_close_reason,
        closed_by=transaction.closed_by,
    )


@router.get("/sessions", response_model=SessionPage)
@user_policy("owner.charging.sessions", "owned", "station_owner")
async def sessions(
    query: Annotated[SessionQuery, Query()],
    actor: CurrentActorDependency,
    scope: RequestScope,
    session: Database,
) -> SessionPage:
    latest = (
        select(
            MeterSample.session_id,
            MeterSample.value,
            MeterSample.timestamp,
            func.row_number()
            .over(
                partition_by=MeterSample.session_id,
                order_by=MeterSample.timestamp.desc(),
            )
            .label("rank"),
        )
        .where(
            MeterSample.measurand == "Energy.Active.Import.Register",
            MeterSample.phase == "",
            MeterSample.location == "Outlet",
        )
        .subquery()
    )
    statement = (
        select(
            ChargingSession,
            Station.name,
            ChargePoint.code,
            Connector.connector_number,
            latest.c.value,
            latest.c.timestamp,
        )
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .outerjoin(
            latest, (latest.c.session_id == ChargingSession.id) & (latest.c.rank == 1)
        )
    )
    owner = scope.owner_id
    if owner is not None:
        statement = statement.where(Station.owner_id == owner)
    if query.state == "open":
        statement = statement.where(ChargingSession.ended_at.is_(None))
    elif query.state == "closed":
        statement = statement.where(ChargingSession.ended_at.is_not(None))
    elif query.state == "review":
        statement = statement.where(
            func.jsonb_array_length(ChargingSession.review_reasons) > 0
        )
    elif query.state == "abnormal":
        statement = statement.where(
            ChargingSession.ended_at.is_(None),
            ChargingSession.abnormal_since.is_not(None),
        )
    total = (
        await session.scalar(select(func.count()).select_from(statement.subquery()))
        or 0
    )
    rows = (
        await session.execute(
            statement.order_by(ChargingSession.id.desc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return SessionPage(
        items=[
            session_row(row[0], row[1], row[2], row[3], row[4], row[5]) for row in rows
        ],
        total=total,
        page=query.page,
        total_pages=(total + query.page_size - 1) // query.page_size,
    )


@router.get("/sessions/{transaction_id}/samples", response_model=SamplePage)
@user_policy("owner.charging.samples", "owned", "station_owner")
async def samples(
    transaction_id: int,
    query: Annotated[SessionQuery, Query()],
    actor: CurrentActorDependency,
    scope: RequestScope,
    session: Database,
) -> SamplePage:
    scoped_query = (
        select(ChargingSession.id)
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .where(ChargingSession.id == transaction_id)
    )
    owner = scope.owner_id
    if owner is not None:
        scoped_query = scoped_query.where(Station.owner_id == owner)
    if await session.scalar(scoped_query) is None:
        raise HTTPException(404, "Không tìm thấy phiên trong phạm vi quản lý.")
    statement = select(MeterSample).where(MeterSample.session_id == transaction_id)
    total = (
        await session.scalar(select(func.count()).select_from(statement.subquery()))
        or 0
    )
    values = await session.scalars(
        statement.order_by(MeterSample.timestamp.desc(), MeterSample.id.desc())
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    )
    return SamplePage(
        items=[SampleResponse.model_validate(value) for value in values],
        total=total,
        page=query.page,
        total_pages=(total + query.page_size - 1) // query.page_size,
    )


@router.post("/sessions/{transaction_id}/close")
@user_policy("ops.sessions.close", "all", "operator")
async def close_session(
    authorization: AuditEvidence,
    transaction_id: int,
    body: ManualCloseRequest,
    actor: CurrentActorDependency,
    scope: RequestScope,
    session: Database,
) -> dict[str, object]:
    charger_id = await session.scalar(
        select(ChargingSession.charge_point_id).where(
            ChargingSession.id == transaction_id
        )
    )
    if charger_id is None:
        raise HTTPException(404, "Không tìm thấy phiên.")
    await session.scalar(
        select(ChargePoint).where(ChargePoint.id == charger_id).with_for_update()
    )
    transaction = await session.scalar(
        select(ChargingSession)
        .where(ChargingSession.id == transaction_id)
        .with_for_update()
    )
    if transaction is None:
        raise HTTPException(404, "Không tìm thấy phiên.")
    await manual_close(
        session, transaction, actor.user_id, body.reason, authorization=authorization
    )
    await session.flush()
    return {
        "id": transaction.id,
        "energy_kwh": str(transaction.energy_kwh),
        "ended_at": transaction.ended_at.isoformat() if transaction.ended_at else None,
    }


@router.get("/sessions/{transaction_id}/events")
@user_policy("owner.charging.session_events", "owned", "station_owner")
async def session_events(
    transaction_id: int,
    actor: CurrentActorDependency,
    scope: RequestScope,
    session: Database,
) -> list[dict[str, object]]:
    scoped_query = (
        select(ChargingSession.id)
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .where(ChargingSession.id == transaction_id)
    )
    owner = scope.owner_id
    if owner is not None:
        scoped_query = scoped_query.where(Station.owner_id == owner)
    if await session.scalar(scoped_query) is None:
        raise HTTPException(404, "Không tìm thấy phiên trong phạm vi quản lý.")
    rows = (
        await session.execute(
            select(ChargingSessionEvent, User.email)
            .outerjoin(User, User.id == ChargingSessionEvent.actor_id)
            .where(ChargingSessionEvent.session_id == transaction_id)
            .order_by(
                ChargingSessionEvent.occurred_at.desc(), ChargingSessionEvent.id.desc()
            )
            .limit(100)
        )
    ).all()
    return [
        {
            "id": str(row[0].id),
            "action": row[0].action,
            "actor": row[1],
            "details": row[0].details,
            "occurred_at": row[0].occurred_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/pending")
@user_policy("owner.charging.pending_messages", "owned", "station_owner")
async def pending_messages(
    actor: CurrentActorDependency, scope: RequestScope, session: Database
) -> list[dict[str, object]]:
    statement = (
        select(PendingChargingMessage, ChargePoint.code)
        .join(ChargePoint, ChargePoint.id == PendingChargingMessage.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
    )
    owner = scope.owner_id
    if owner is not None:
        statement = statement.where(Station.owner_id == owner)
    rows = (
        await session.execute(
            statement.order_by(PendingChargingMessage.received_at.desc()).limit(100)
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "charge_point_code": code,
            "action": item.action,
            "reason": item.reason,
            "transaction_id": item.payload.get("transactionId"),
            "received_at": item.received_at.isoformat(),
        }
        for item, code in rows
    ]
