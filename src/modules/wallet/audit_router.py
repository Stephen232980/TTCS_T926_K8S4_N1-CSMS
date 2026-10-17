"""S-56: admin-only projection over the existing immutable audit evidence."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import String, and_, cast, func, or_, select

from src.modules.identity.admin_router import AdminAccountRoute
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import authorize_request
from src.modules.reservations.models import Reservation
from src.modules.wallet.admin_router import Database
from src.modules.wallet.models import Wallet, WalletAudit, WalletLedger
from src.platform.audit.models import AuditLog

Action = Literal[
    "wallet.manual_topup",
    "wallet.adjusted",
    "wallet.cache_repaired",
    "wallet.unlocked",
    "reservation.fee_decided",
]
ACTIONS = (
    "wallet.manual_topup",
    "wallet.adjusted",
    "wallet.cache_repaired",
    "wallet.unlocked",
    "reservation.fee_decided",
)
router = APIRouter(
    prefix="/api/v1/admin/wallet-audit",
    tags=["admin-wallet-audit"],
    route_class=AdminAccountRoute,
    dependencies=[Depends(authorize_request)],
)


class AuditQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    driver_id: UUID | None = None
    wallet_id: UUID | None = None
    action: Action | None = None
    from_at: AwareDatetime | None = None
    to_at: AwareDatetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=50)

    @model_validator(mode="after")
    def window(self) -> Self:
        if self.from_at and self.to_at and self.from_at > self.to_at:
            raise ValueError("Thời gian bắt đầu phải trước thời gian kết thúc")
        return self


class AuditEntry(BaseModel):
    id: UUID
    actor_id: UUID | None
    driver_id: UUID | None
    wallet_id: UUID | None
    action: str
    occurred_at: datetime
    amount_vnd: int | None
    before_balance_vnd: int | None
    after_balance_vnd: int | None
    reason: str | None
    legacy: bool
    ledger_id: int | None
    reference_type: str | None
    reference_id: str | None
    reservation_id: UUID | None
    before_decision: str | None
    decision: str | None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    page: int
    page_size: int
    total: int
    total_pages: int


@router.get("", response_model=AuditPage)
@user_policy("admin.wallet.audit", "all", "admin")
async def wallet_audit(
    db: Database, query: Annotated[AuditQuery, Query()]
) -> AuditPage:
    statement = (
        select(AuditLog, Wallet, WalletAudit, WalletLedger, Reservation)
        .outerjoin(
            WalletAudit,
            and_(
                AuditLog.object_type == "wallet_audit",
                AuditLog.object_id == cast(WalletAudit.id, String),
            ),
        )
        .outerjoin(
            Reservation,
            and_(
                AuditLog.object_type == "reservation",
                AuditLog.object_id == cast(Reservation.id, String),
            ),
        )
        .outerjoin(
            Wallet,
            or_(
                and_(
                    AuditLog.object_type == "wallet",
                    AuditLog.object_id == cast(Wallet.id, String),
                ),
                WalletAudit.wallet_id == Wallet.id,
                and_(
                    AuditLog.object_type == "reservation",
                    Reservation.driver_id == Wallet.driver_id,
                ),
            ),
        )
        .outerjoin(
            WalletLedger,
            or_(
                cast(WalletLedger.id, String) == AuditLog.data["ledger_id"].as_string(),
                and_(
                    AuditLog.action == "wallet.adjusted",
                    WalletLedger.reference_type == "audit",
                    WalletLedger.reference_id == AuditLog.object_id,
                ),
            ),
        )
        .where(AuditLog.action.in_(ACTIONS))
    )
    if query.driver_id:
        statement = statement.where(Wallet.driver_id == query.driver_id)
    if query.wallet_id:
        statement = statement.where(Wallet.id == query.wallet_id)
    if query.action:
        statement = statement.where(AuditLog.action == query.action)
    if query.from_at:
        statement = statement.where(AuditLog.occurred_at >= query.from_at)
    if query.to_at:
        statement = statement.where(AuditLog.occurred_at <= query.to_at)
    total = await db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = await db.execute(
        statement.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    )
    items = []
    for audit, wallet, evidence, ledger, booking in rows:
        data = audit.data
        items.append(
            AuditEntry(
                id=audit.id,
                actor_id=audit.actor_id,
                driver_id=wallet.driver_id if wallet else None,
                wallet_id=wallet.id if wallet else None,
                action=audit.action,
                occurred_at=audit.occurred_at,
                amount_vnd=ledger.amount_vnd if ledger else data.get("amount_vnd"),
                before_balance_vnd=data.get(
                    "before_balance_vnd",
                    evidence.before_balance_vnd
                    if evidence
                    else (
                        ledger.balance_after_vnd - ledger.amount_vnd if ledger else None
                    ),
                ),
                after_balance_vnd=data.get(
                    "after_balance_vnd",
                    evidence.after_balance_vnd
                    if evidence
                    else (ledger.balance_after_vnd if ledger else None),
                ),
                reason=data.get("reason", evidence.reason if evidence else None),
                legacy=data.get("audit_version") != 1,
                ledger_id=ledger.id if ledger else None,
                reference_type=ledger.reference_type if ledger else None,
                reference_id=ledger.reference_id if ledger else None,
                reservation_id=booking.id if booking else None,
                before_decision=data.get("before_decision"),
                decision=data.get("decision"),
            )
        )
    return AuditPage(
        items=items,
        page=query.page,
        page_size=query.page_size,
        total=total,
        total_pages=(total + query.page_size - 1) // query.page_size,
    )
