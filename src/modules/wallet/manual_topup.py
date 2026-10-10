"""Administrative receipts credit a wallet once, with atomic audit evidence."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import Role, User, UserRole
from src.modules.wallet.exceptions import (
    WalletAdminRequiredError,
    WalletAmountError,
    WalletLedgerConflictError,
    WalletNotFoundError,
)
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.service import MAX_VND, ghi_so_cai
from src.platform.audit.service import ghi_nhat_ky


class ManualTopupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_vnd: Annotated[int, Field(strict=True, gt=0, le=MAX_VND)]
    receipt_code: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=128
        ),
    ]


class ManualTopupResponse(BaseModel):
    ledger_id: int
    wallet_id: UUID
    driver_id: UUID
    amount_vnd: int
    balance_after_vnd: int
    receipt_code: str
    actor_id: UUID
    created_at: datetime


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
    wallet = await session.scalar(
        select(Wallet)
        .where(Wallet.driver_id == driver_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if wallet is None:
        raise WalletNotFoundError("Driver wallet does not exist")
    existing = await session.scalar(
        select(WalletLedger.id).where(
            WalletLedger.entry_type == "manual_topup",
            WalletLedger.reference_id == request.receipt_code,
        )
    )
    if existing is not None:
        raise WalletLedgerConflictError("Receipt already used")
    async with session.begin_nested():
        entry = await ghi_so_cai(
            session,
            wallet_id=wallet.id,
            entry_type="manual_topup",
            amount_vnd=request.amount_vnd,
            reference_type="manual_topup",
            reference_id=request.receipt_code,
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
            },
            permission=authorization.permission,
            actor_roles=authorization.roles,
        )
        return ManualTopupResponse(
            ledger_id=entry.id,
            wallet_id=wallet.id,
            driver_id=driver_id,
            amount_vnd=entry.amount_vnd,
            balance_after_vnd=entry.balance_after_vnd,
            receipt_code=entry.reference_id,
            actor_id=actor_id,
            created_at=entry.created_at,
        )
