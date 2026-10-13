"""Administrative receipts credit a wallet once, with atomic audit evidence."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import Role, User, UserRole
from src.modules.wallet.exceptions import (
    ManualTopupRequestConflictError,
    WalletAdminRequiredError,
    WalletAmountError,
    WalletLedgerConflictError,
    WalletNotFoundError,
)
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.service import MAX_VND, ghi_so_cai
from src.platform.audit.models import AuditLog
from src.platform.audit.service import ghi_nhat_ky


class ManualTopupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_vnd: Annotated[int, Field(strict=True, gt=0, le=MAX_VND)]
    receipt_code: Annotated[
        str | None,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=128
        ),
    ] = None
    request_id: UUID | None = None
    payment_received: StrictBool | None = None
    external_reference: Annotated[
        str | None,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=128
        ),
    ] = None

    @model_validator(mode="after")
    def receipt_mode(self) -> Self:
        if self.receipt_code is not None:
            if self.receipt_code.upper().startswith("PT-AUTO-"):
                raise ValueError("PT-AUTO- is reserved for generated receipts")
            if (
                self.request_id is not None
                or self.payment_received is not None
                or self.external_reference is not None
            ):
                raise ValueError(
                    "Do not mix a supplied receipt with generated-receipt fields"
                )
        elif self.request_id is None or self.payment_received is not True:
            raise ValueError(
                "Generated receipts require request_id and payment_received=true"
            )
        return self


class ManualTopupResponse(BaseModel):
    ledger_id: int
    wallet_id: UUID
    driver_id: UUID
    amount_vnd: int
    balance_after_vnd: int
    receipt_code: str
    actor_id: UUID
    created_at: datetime
    request_id: UUID | None = None
    payment_received: bool | None = None
    external_reference: str | None = None


async def nap_tay(
    session: AsyncSession,
    *,
    driver_id: UUID,
    actor_id: UUID,
    request: ManualTopupRequest,
    authorization: AuthorizationEvidence,
) -> ManualTopupResponse:
    admin = await session.scalar(
        select(User.id)
        .join(UserRole)
        .join(Role)
        .where(User.id == actor_id, User.status == "active", Role.code == "admin")
    )
    if admin is None:
        raise WalletAdminRequiredError("An active administrator is required")
    if request.amount_vnd > settings.wallet_manual_topup_max_vnd:
        raise WalletAmountError("Amount exceeds manual topup limit")
    receipt_code = request.receipt_code
    if request.request_id is not None:
        receipt_code = "PT-AUTO-" + request.request_id.hex
        # Serialize identical keys across different wallets before taking wallet locks.
        key = int.from_bytes(request.request_id.bytes[:8], "big", signed=True)
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    assert receipt_code is not None
    wallet = await session.scalar(
        select(Wallet)
        .where(Wallet.driver_id == driver_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if wallet is None:
        raise WalletNotFoundError("Driver wallet does not exist")
    existing = await session.scalar(
        select(WalletLedger).where(
            WalletLedger.entry_type == "manual_topup",
            WalletLedger.reference_id == receipt_code,
        )
    )
    if existing is not None:
        if request.request_id is None:
            raise WalletLedgerConflictError("Receipt already used")
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "wallet.manual_topup",
                AuditLog.object_id == str(wallet.id),
                AuditLog.data["ledger_id"].as_integer() == existing.id,
            )
        )
        if (
            existing.wallet_id != wallet.id
            or existing.actor_id != actor_id
            or existing.amount_vnd != request.amount_vnd
            or audit is None
            or audit.data.get("request_id") != str(request.request_id)
            or audit.data.get("external_reference") != request.external_reference
            or audit.data.get("payment_received") is not True
        ):
            raise ManualTopupRequestConflictError(
                "Generated receipt request conflicts with original"
            )
        return _response(existing, driver_id, request)

    async with session.begin_nested():
        entry = await ghi_so_cai(
            session,
            wallet_id=wallet.id,
            entry_type="manual_topup",
            amount_vnd=request.amount_vnd,
            reference_type="manual_topup",
            reference_id=receipt_code,
            actor_id=actor_id,
        )
        await ghi_nhat_ky(
            session,
            actor_id=actor_id,
            action="wallet.manual_topup",
            object_type="wallet",
            object_id=str(wallet.id),
            data={
                "ledger_id": entry.id,
                "amount_vnd": entry.amount_vnd,
                "receipt_code": entry.reference_id,
                **(
                    {
                        "request_id": str(request.request_id),
                        "payment_received": True,
                        "external_reference": request.external_reference,
                    }
                    if request.request_id is not None
                    else {}
                ),
            },
            permission=authorization.permission,
            actor_roles=authorization.roles,
        )
        return _response(entry, driver_id, request)


def _response(
    entry: WalletLedger, driver_id: UUID, request: ManualTopupRequest
) -> ManualTopupResponse:
    assert entry.actor_id is not None
    return ManualTopupResponse(
        ledger_id=entry.id,
        wallet_id=entry.wallet_id,
        driver_id=driver_id,
        amount_vnd=entry.amount_vnd,
        balance_after_vnd=entry.balance_after_vnd,
        receipt_code=entry.reference_id,
        actor_id=entry.actor_id,
        created_at=entry.created_at,
        request_id=request.request_id,
        payment_received=request.payment_received,
        external_reference=request.external_reference,
    )
