"""Accountant-only financial lookup. GET never creates invoices or debits wallets."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.billing.driver_router import LineResponse
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import authorize_request
from src.modules.identity.models import User
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/accounting/finance",
    tags=["accounting-finance"],
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]
FinancialStatus = Literal[
    "in_progress",
    "awaiting_unplug",
    "needs_review",
    "pending_invoice",
    "pending_settlement",
    "settled",
    "legacy_exempt",
]


class FinancialQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    q: str = Field(default="", max_length=160)
    station_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: Literal[
        "all",
        "in_progress",
        "awaiting_unplug",
        "needs_review",
        "pending_invoice",
        "pending_settlement",
        "settled",
        "legacy_exempt",
    ] = "all"
    attention: bool = False
    age: Literal["all", "under_hour", "under_day", "under_week", "over_week"] = "all"

    @model_validator(mode="after")
    def validate_range(self) -> "FinancialQuery":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Ngày bắt đầu phải trước hoặc bằng ngày kết thúc")
        if self.date_to == date.max:
            raise ValueError("Ngày kết thúc nằm ngoài phạm vi hỗ trợ")
        return self


class FinancialSession(BaseModel):
    session_id: int
    station_id: UUID
    station_name: str
    charge_point_code: str
    connector_number: int
    driver_email: str | None
    started_at: datetime
    ended_at: datetime | None
    connector_released_at: datetime | None
    energy_kwh: Decimal | None
    status: FinancialStatus
    review_reasons: list[str]
    invoice_id: UUID | None
    invoice_created_at: datetime | None
    invoice_total_vnd: str | None
    debited_vnd: str
    ledger_id: int | None
    debited_at: datetime | None
    settlement_completed_at: datetime | None
    settlement_reason: str | None


class FinancialSummary(BaseModel):
    sessions: int
    invoices: int
    invoice_total_vnd: str
    debited_total_vnd: str
    awaiting_settlement: int


class FinancialPage(BaseModel):
    items: list[FinancialSession]
    total: int
    page: int
    total_pages: int
    summary: FinancialSummary


class FinancialDetail(FinancialSession):
    rounding_rule: str | None
    lines: list[LineResponse]
    ledger_amount_vnd: str | None
    ledger_reference_type: str | None


def financial_rows() -> Any:
    """One row per session; charging_debit/reference_id is a unique ledger key."""
    same_driver = and_(
        Invoice.driver_id == ChargingSession.driver_id,
        Invoice.station_id == Station.id,
    )
    valid_debit = and_(
        Wallet.driver_id == ChargingSession.driver_id,
        WalletLedger.reference_type == "charging_session",
        WalletLedger.amount_vnd < 0,
        -WalletLedger.amount_vnd == Invoice.total_vnd,
        same_driver,
    )
    valid_zero = and_(Invoice.total_vnd == 0, same_driver, WalletLedger.id.is_(None))
    valid_completion = or_(
        and_(ChargingSession.settlement_reason == "debited", valid_debit),
        and_(ChargingSession.settlement_reason == "zero_invoice", valid_zero),
    )
    legacy = and_(
        ChargingSession.settlement_completed_at.is_not(None),
        ChargingSession.settlement_reason == "legacy_exempt",
    )
    inconsistent = or_(
        and_(Invoice.id.is_not(None), ~func.coalesce(same_driver, False)),
        and_(WalletLedger.id.is_not(None), ~func.coalesce(valid_debit, False)),
        and_(
            ChargingSession.settlement_completed_at.is_not(None),
            ~legacy,
            ~func.coalesce(valid_completion, False),
        ),
    )
    status = case(
        (inconsistent, "needs_review"),
        (legacy, "legacy_exempt"),
        (
            and_(
                ChargingSession.settlement_completed_at.is_not(None), valid_completion
            ),
            "settled",
        ),
        (func.jsonb_array_length(ChargingSession.review_reasons) > 0, "needs_review"),
        (ChargingSession.ended_at.is_(None), "in_progress"),
        (
            and_(
                ChargingSession.billing_lifecycle_version == 1,
                ChargingSession.connector_released_at.is_(None),
            ),
            "awaiting_unplug",
        ),
        (Invoice.id.is_(None), "pending_invoice"),
        else_="pending_settlement",
    ).label("financial_status")
    return (
        select(
            ChargingSession,
            Invoice,
            Station,
            ChargePoint,
            User.email,
            WalletLedger,
            status,
            case((valid_debit, -WalletLedger.amount_vnd), else_=0).label("debited_vnd"),
            inconsistent.label("inconsistent"),
            Connector.connector_number,
        )
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .outerjoin(User, User.id == ChargingSession.driver_id)
        .outerjoin(Invoice, Invoice.session_id == ChargingSession.id)
        .outerjoin(
            WalletLedger,
            and_(
                WalletLedger.entry_type == "charging_debit",
                WalletLedger.reference_id == cast(ChargingSession.id, String),
            ),
        )
        .outerjoin(Wallet, Wallet.id == WalletLedger.wallet_id)
    )


def filtered_rows(query: FinancialQuery, *, invoices_only: bool = False) -> Any:
    statement = financial_rows()
    if invoices_only:
        statement = statement.where(Invoice.id.is_not(None))
    if query.station_id:
        statement = statement.where(Station.id == query.station_id)
    if query.q.strip():
        pattern = (
            "%"
            + query.q.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            + "%"
        )
        statement = statement.where(
            or_(
                *(
                    column.ilike(pattern, escape="\\")
                    for column in [
                        Station.name,
                        ChargePoint.code,
                        User.email,
                        cast(ChargingSession.id, String),
                        cast(Invoice.id, String),
                    ]
                )
            )
        )
    timezone = ZoneInfo("Asia/Ho_Chi_Minh")
    date_column = Invoice.created_at if invoices_only else ChargingSession.started_at
    if query.date_from:
        statement = statement.where(
            date_column >= datetime.combine(query.date_from, time.min, timezone)
        )
    if query.date_to:
        statement = statement.where(
            date_column
            < datetime.combine(query.date_to + timedelta(days=1), time.min, timezone)
        )
    status = statement.selected_columns.financial_status
    if query.status != "all":
        statement = statement.where(status == query.status)
    if query.attention:
        statement = statement.where(
            or_(
                status == "needs_review",
                and_(
                    ChargingSession.ended_at.is_not(None),
                    status.in_(
                        ["awaiting_unplug", "pending_invoice", "pending_settlement"]
                    ),
                ),
            )
        )
    if query.age != "all":
        now = datetime.now(UTC)
        origin = func.coalesce(ChargingSession.ended_at, ChargingSession.started_at)
        bounds = {
            "under_hour": (None, timedelta(hours=1)),
            "under_day": (timedelta(hours=1), timedelta(days=1)),
            "under_week": (timedelta(days=1), timedelta(days=7)),
            "over_week": (timedelta(days=7), None),
        }
        lower, upper = bounds[query.age]
        if lower is not None:
            statement = statement.where(origin <= now - lower)
        if upper is not None:
            statement = statement.where(origin > now - upper)
    return statement


def present(row: Any) -> FinancialSession:
    (
        charging,
        invoice,
        station,
        charger,
        email,
        ledger,
        status,
        debited,
        inconsistent,
        connector_number,
    ) = row
    reasons = list(charging.review_reasons)
    if inconsistent and "settlement_ledger_mismatch" not in reasons:
        reasons.append("settlement_ledger_mismatch")
    return FinancialSession(
        session_id=charging.id,
        station_id=station.id,
        station_name=station.name,
        charge_point_code=charger.code,
        connector_number=connector_number,
        driver_email=email,
        started_at=charging.started_at,
        ended_at=charging.ended_at,
        connector_released_at=charging.connector_released_at,
        energy_kwh=charging.energy_kwh,
        status=status,
        review_reasons=reasons,
        invoice_id=invoice.id if invoice else None,
        invoice_created_at=invoice.created_at if invoice else None,
        invoice_total_vnd=str(invoice.total_vnd) if invoice else None,
        debited_vnd=str(debited),
        ledger_id=ledger.id if ledger else None,
        debited_at=ledger.created_at if ledger else None,
        settlement_completed_at=charging.settlement_completed_at,
        settlement_reason=charging.settlement_reason,
    )


async def list_finances(
    db: AsyncSession, query: FinancialQuery, *, invoices_only: bool = False
) -> FinancialPage:
    statement = filtered_rows(query, invoices_only=invoices_only)
    # Aggregate the complete filtered set, not just the visible page.
    counts = (
        await db.execute(
            statement.with_only_columns(
                func.count(ChargingSession.id),
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.total_vnd), 0),
                func.coalesce(func.sum(statement.selected_columns.debited_vnd), 0),
                func.count().filter(
                    statement.selected_columns.financial_status.in_(
                        [
                            "awaiting_unplug",
                            "pending_invoice",
                            "pending_settlement",
                            "needs_review",
                        ]
                    )
                ),
                maintain_column_froms=True,
            )
        )
    ).one()
    rows = (
        await db.execute(
            statement.order_by(
                *(
                    [
                        case(
                            (
                                statement.selected_columns.financial_status
                                == "needs_review",
                                0,
                            ),
                            else_=1,
                        ),
                        func.coalesce(
                            ChargingSession.ended_at, ChargingSession.started_at
                        ),
                        ChargingSession.id,
                    ]
                    if query.attention
                    else (
                        [Invoice.created_at.desc(), Invoice.id.desc()]
                        if invoices_only
                        else [ChargingSession.id.desc()]
                    )
                )
            )
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    total = counts[0]
    return FinancialPage(
        items=[present(row) for row in rows],
        total=total,
        page=query.page,
        total_pages=max(1, (total + query.page_size - 1) // query.page_size),
        summary=FinancialSummary(
            sessions=total,
            invoices=counts[1],
            invoice_total_vnd=str(counts[2]),
            debited_total_vnd=str(counts[3]),
            awaiting_settlement=counts[4],
        ),
    )


@router.get("/sessions", response_model=FinancialPage)
@user_policy("accounting.finance.read", "all", "accountant")
async def sessions(
    db: Database, query: Annotated[FinancialQuery, Query()]
) -> FinancialPage:
    return await list_finances(db, query)


@router.get("/invoices", response_model=FinancialPage)
@user_policy("accounting.finance.read", "all", "accountant")
async def invoices(
    db: Database, query: Annotated[FinancialQuery, Query()]
) -> FinancialPage:
    return await list_finances(db, query, invoices_only=True)


@router.get("/stations")
@user_policy("accounting.finance.read", "all", "accountant")
async def stations(db: Database) -> dict[str, list[dict[str, str]]]:
    rows = (
        await db.execute(
            select(Station.id, Station.name)
            .join(ChargePoint)
            .join(ChargingSession)
            .distinct()
            .order_by(Station.name, Station.id)
        )
    ).all()
    return {"items": [{"id": str(id_), "name": name} for id_, name in rows]}


@router.get("/insights/{area}")
@user_policy("accounting.finance.read", "all", "accountant")
async def insights(
    area: Literal["sessions", "invoices", "reconciliation"],
    db: Database,
    query: Annotated[FinancialQuery, Query()],
) -> dict[str, Any]:
    """Full-filter aggregates; session cohorts, never invoice/debit cash dates."""
    if area == "reconciliation":
        query = query.model_copy(update={"attention": True})
    statement = filtered_rows(query, invoices_only=area == "invoices")
    cohort = statement.with_only_columns(
        ChargingSession.id.label("session_id"),
        (
            Invoice.created_at if area == "invoices" else ChargingSession.started_at
        ).label("started_at"),
        func.coalesce(ChargingSession.ended_at, ChargingSession.started_at).label(
            "age_origin"
        ),
        Station.id.label("station_id"),
        Station.name.label("station_name"),
        Invoice.id.label("invoice_id"),
        func.coalesce(Invoice.total_vnd, 0).label("invoice_vnd"),
        statement.selected_columns.debited_vnd,
        statement.selected_columns.financial_status,
        maintain_column_froms=True,
    ).subquery()
    c = cohort.c
    span = (
        await db.execute(select(func.min(c.started_at), func.max(c.started_at)))
    ).one()
    grain = "month" if span[0] and (span[1] - span[0]).days > 62 else "day"
    period = func.date_trunc(grain, func.timezone("Asia/Ho_Chi_Minh", c.started_at))
    daily = (
        await db.execute(
            select(
                period.label("period"),
                func.count(),
                func.sum(c.invoice_vnd),
                func.sum(c.debited_vnd),
            )
            .group_by(period)
            .order_by(period)
        )
    ).all()
    stations_data = (
        await db.execute(
            select(
                c.station_id,
                c.station_name,
                func.count(),
                func.sum(c.invoice_vnd),
                func.sum(c.debited_vnd),
            )
            .group_by(c.station_id, c.station_name)
            .order_by(func.sum(c.invoice_vnd).desc(), c.station_name)
        )
    ).all()
    statuses = (
        await db.execute(
            select(c.financial_status, func.count(), func.sum(c.invoice_vnd)).group_by(
                c.financial_status
            )
        )
    ).all()
    now = datetime.now(UTC)
    age = case(
        (c.age_origin > now - timedelta(hours=1), "under_hour"),
        (c.age_origin > now - timedelta(days=1), "under_day"),
        (c.age_origin > now - timedelta(days=7), "under_week"),
        else_="over_week",
    )
    aging = (
        await db.execute(
            select(age, func.count(), func.sum(c.invoice_vnd)).group_by(age)
        )
    ).all()
    fees = (
        await db.execute(
            select(InvoiceLine.line_type, func.sum(InvoiceLine.amount_vnd))
            .join(cohort, c.invoice_id == InvoiceLine.invoice_id)
            .group_by(InvoiceLine.line_type)
        )
    ).all()
    return {
        "grain": grain,
        "generated_at": now,
        "timeline": [
            {
                "period": row[0].date().isoformat(),
                "sessions": row[1],
                "invoice_vnd": str(row[2]),
                "debited_vnd": str(row[3]),
            }
            for row in daily
        ],
        "stations": [
            {
                "id": str(row[0]),
                "name": row[1],
                "sessions": row[2],
                "invoice_vnd": str(row[3]),
                "debited_vnd": str(row[4]),
            }
            for row in stations_data
        ],
        "statuses": [
            {"status": row[0], "count": row[1], "invoice_vnd": str(row[2])}
            for row in statuses
        ],
        "aging": [
            {"bucket": row[0], "count": row[1], "invoice_vnd": str(row[2])}
            for row in aging
        ],
        "fees": [{"type": row[0], "amount_vnd": str(row[1])} for row in fees],
    }


@router.get("/sessions/{session_id}", response_model=FinancialDetail)
@user_policy("accounting.finance.read", "all", "accountant")
async def detail(session_id: int, db: Database) -> FinancialDetail:
    row = (
        await db.execute(financial_rows().where(ChargingSession.id == session_id))
    ).first()
    if row is None:
        raise HTTPException(404, "Không tìm thấy phiên sạc")
    invoice = row[1]
    ledger = row[5]
    lines = (
        (
            await db.scalars(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id == invoice.id)
                .order_by(InvoiceLine.started_at, InvoiceLine.line_type, InvoiceLine.id)
            )
        ).all()
        if invoice
        else []
    )
    return FinancialDetail(
        **present(row).model_dump(),
        rounding_rule=invoice.rounding_rule if invoice else None,
        lines=[
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
        ],
        ledger_amount_vnd=str(ledger.amount_vnd) if ledger else None,
        ledger_reference_type=ledger.reference_type if ledger else None,
    )
