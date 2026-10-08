from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import RequestScope, authorize_request
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.wallet.admin_router import Database
from src.modules.wallet.administration import dieu_chinh_vi, mo_khoa_vi, sua_so_du_cache
from src.modules.wallet.exceptions import (
    WalletAdjustmentAuditError,
    WalletAdminRequiredError,
    WalletAmountError,
    WalletLedgerConflictError,
    WalletNotFoundError,
    WalletReconciliationError,
)
from src.modules.wallet.service import MAX_VND, MIN_VND

router = APIRouter(
    prefix="/api/v1/admin/wallets",
    tags=["admin-wallet"],
    route_class=PolicyRoute,
    dependencies=[Depends(authorize_request)],
)


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=500
        ),
    ]


class AdjustmentRequest(RepairRequest):
    amount_vnd: Annotated[int, Field(strict=True, ge=MIN_VND, le=MAX_VND)]
    audit_id: UUID

    @field_validator("amount_vnd")
    @classmethod
    def nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Adjustment must be nonzero")
        return value


class WalletState(BaseModel):
    wallet_id: UUID
    balance_vnd: int
    status: str


class AdjustmentResult(BaseModel):
    ledger_id: int
    wallet_id: UUID
    audit_id: UUID
    amount_vnd: int
    balance_after_vnd: int


@asynccontextmanager
async def command_errors() -> AsyncIterator[None]:
    try:
        yield
    except WalletAdminRequiredError as error:
        raise HTTPException(403, "permission_denied") from error
    except WalletNotFoundError as error:
        raise HTTPException(404, "resource_not_found") from error
    except WalletReconciliationError as error:
        raise HTTPException(
            409, {"code": "wallet_checks_failed", "checks": error.checks}
        ) from error
    except (WalletAdjustmentAuditError, WalletLedgerConflictError) as error:
        raise HTTPException(409, "adjustment_conflict") from error
    except (WalletAmountError, ValueError) as error:
        raise HTTPException(422, str(error)) from error


@router.post("/{wallet_id}/repair-cache", response_model=WalletState)
@user_policy("admin.wallet.repair_cache", "all", "admin")
async def repair_cache(
    wallet_id: UUID, body: RepairRequest, scope: RequestScope, db: Database
) -> WalletState:
    async with command_errors():
        wallet = await sua_so_du_cache(
            db, wallet_id=wallet_id, actor_id=scope.actor_id, reason=body.reason
        )
        await db.commit()
        return WalletState(
            wallet_id=wallet.id, balance_vnd=wallet.balance_vnd, status=wallet.status
        )


@router.post("/{wallet_id}/unlock", response_model=WalletState)
@user_policy("admin.wallet.unlock", "all", "admin")
async def unlock(wallet_id: UUID, scope: RequestScope, db: Database) -> WalletState:
    async with command_errors():
        wallet = await mo_khoa_vi(db, wallet_id=wallet_id, actor_id=scope.actor_id)
        await db.commit()
        return WalletState(
            wallet_id=wallet.id, balance_vnd=wallet.balance_vnd, status=wallet.status
        )


@router.post(
    "/{wallet_id}/adjustments", response_model=AdjustmentResult, status_code=201
)
@user_policy("admin.wallet.adjust", "all", "admin")
async def adjust(
    wallet_id: UUID, body: AdjustmentRequest, scope: RequestScope, db: Database
) -> AdjustmentResult:
    async with command_errors():
        entry = await dieu_chinh_vi(
            db,
            wallet_id=wallet_id,
            actor_id=scope.actor_id,
            amount_vnd=body.amount_vnd,
            reason=body.reason,
            audit_id=body.audit_id,
        )
        await db.commit()
        return AdjustmentResult(
            ledger_id=entry.id,
            wallet_id=entry.wallet_id,
            audit_id=body.audit_id,
            amount_vnd=entry.amount_vnd,
            balance_after_vnd=entry.balance_after_vnd,
        )
