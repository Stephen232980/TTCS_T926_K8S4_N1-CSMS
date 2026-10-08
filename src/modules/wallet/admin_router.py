from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    AuditEvidence,
    RequestScope,
    authorize_request,
)
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.wallet.exceptions import (
    WalletAdminRequiredError,
    WalletAmountError,
    WalletLedgerConflictError,
    WalletLockedError,
    WalletNotFoundError,
)
from src.modules.wallet.manual_topup import (
    ManualTopupRequest,
    ManualTopupResponse,
    nap_tay,
)
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/drivers",
    tags=["admin-wallet"],
    route_class=PolicyRoute,
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "/{driver_id}/wallet/manual-topups",
    response_model=ManualTopupResponse,
    status_code=201,
    responses={
        401: {"description": "Chưa đăng nhập"},
        403: {"description": "Chỉ quản trị viên được nạp tay"},
        404: {"description": "Không tìm thấy ví tài xế"},
        409: {"description": "Phiếu thu đã dùng hoặc ví bị khoá"},
    },
)
@user_policy("admin.wallet.manual_topup", "all", "admin")
async def manual_topup(
    driver_id: UUID,
    request: ManualTopupRequest,
    scope: RequestScope,
    db: Database,
    authorization: AuditEvidence,
) -> ManualTopupResponse:
    try:
        response = await nap_tay(
            db,
            driver_id=driver_id,
            actor_id=scope.actor_id,
            request=request,
            authorization=authorization,
        )
        await db.commit()
        return response
    except WalletAdminRequiredError as error:
        raise HTTPException(403, "permission_denied") from error
    except WalletNotFoundError as error:
        raise HTTPException(404, "resource_not_found") from error
    except WalletLedgerConflictError as error:
        raise HTTPException(409, "receipt_already_used") from error
    except WalletLockedError as error:
        raise HTTPException(409, "wallet_locked") from error
    except WalletAmountError as error:
        raise HTTPException(
            422,
            [{"loc": ["body", "amount_vnd"], "msg": str(error), "type": "value_error"}],
        ) from error
