"""Read immutable invoice snapshots; never calculate or settle on a GET."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import CurrentActorDependency, authorize_request
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.stations.models import ChargePoint, Station
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/driver",
    tags=["driver-invoices"],
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]
InvoiceStatus = Literal["ready", "pending", "needs_review", "in_progress"]


class LineResponse(BaseModel):
    id: UUID
    line_type: str
    local_date: date
    started_at: datetime
    ended_at: datetime
    energy_kwh: Decimal
    rate_vnd: str
    band_label: str
    interpolated: bool
    tariff_id: UUID
    amount_vnd: str


class InvoiceSummary(BaseModel):
    session_id: int
    status: InvoiceStatus
    station_name: str
    ended_at: datetime | None
    total_vnd: str | None = None


class InvoiceResponse(InvoiceSummary):
    invoice_id: UUID | None = None
    created_at: datetime | None = None
    rounding_rule: str | None = None
    lines: list[LineResponse] = []


class InvoiceList(BaseModel):
    items: list[InvoiceSummary]
    next_cursor: int | None


def invoice_status(charging: ChargingSession, invoice: Invoice | None) -> InvoiceStatus:
    if charging.review_reasons or (invoice and invoice.driver_id != charging.driver_id):
        return "needs_review"
    if charging.ended_at is None:
        return "in_progress"
    return "ready" if invoice else "pending"


@router.get("/invoices", response_model=InvoiceList)
@user_policy("driver.invoice.view", "own_wallet", "driver")
async def list_invoices(
    actor: CurrentActorDependency,
    db: Database,
    cursor: int | None = Query(None, gt=0),
    limit: int = Query(20, ge=1, le=50),
) -> InvoiceList:
    statement = (
        select(ChargingSession, Invoice, Station.name)
        .join(ChargePoint, ChargingSession.charge_point_id == ChargePoint.id)
        .join(Station, ChargePoint.station_id == Station.id)
        .outerjoin(Invoice, Invoice.session_id == ChargingSession.id)
        .where(
            ChargingSession.driver_id == actor.user_id,
            ChargingSession.ended_at.is_not(None),
        )
        .order_by(ChargingSession.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(ChargingSession.id < cursor)
    rows = (await db.execute(statement)).all()
    items = []
    for charging, invoice, station_name in rows[:limit]:
        state = invoice_status(charging, invoice)
        items.append(
            InvoiceSummary(
                session_id=charging.id,
                status=state,
                station_name=station_name,
                ended_at=charging.ended_at,
                total_vnd=str(invoice.total_vnd)
                if state == "ready" and invoice
                else None,
            )
        )
    return InvoiceList(
        items=items,
        next_cursor=items[-1].session_id if len(rows) > limit else None,
    )


@router.get("/charging/sessions/{session_id}/invoice", response_model=InvoiceResponse)
@user_policy("driver.invoice.view", "own_wallet", "driver")
async def get_invoice(
    session_id: int, actor: CurrentActorDependency, db: Database
) -> InvoiceResponse:
    charging = await db.get(ChargingSession, session_id)
    if charging is None:
        raise HTTPException(404, "Không tìm thấy phiên sạc")
    # Check the session before looking up an invoice, including missing invoices.
    if charging.driver_id != actor.user_id:
        raise HTTPException(403, "Không có quyền xem hóa đơn của phiên này")
    invoice = await db.scalar(select(Invoice).where(Invoice.session_id == session_id))
    station_name = await db.scalar(
        select(Station.name)
        .join(ChargePoint, ChargePoint.station_id == Station.id)
        .where(ChargePoint.id == charging.charge_point_id)
    )
    result = InvoiceResponse(
        session_id=session_id,
        status=invoice_status(charging, invoice),
        station_name=station_name or "Trạm sạc",
        ended_at=charging.ended_at,
    )
    if result.status != "ready" or invoice is None:
        return result
    if invoice.driver_id != actor.user_id:
        raise HTTPException(403, "Không có quyền xem hóa đơn này")
    lines = (
        await db.scalars(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice.id)
            .order_by(InvoiceLine.started_at, InvoiceLine.line_type, InvoiceLine.id)
        )
    ).all()
    result.invoice_id = invoice.id
    result.created_at = invoice.created_at
    result.total_vnd = str(invoice.total_vnd)
    result.rounding_rule = invoice.rounding_rule
    result.lines = [
        LineResponse(
            id=line.id,
            line_type=line.line_type,
            local_date=line.local_date,
            started_at=line.started_at,
            ended_at=line.ended_at,
            energy_kwh=line.energy_wh / Decimal(1000),
            rate_vnd=str(line.rate_vnd),
            band_label=line.band_label,
            interpolated=line.interpolated,
            tariff_id=line.tariff_id,
            amount_vnd=str(line.amount_vnd),
        )
        for line in lines
    ]
    return result
