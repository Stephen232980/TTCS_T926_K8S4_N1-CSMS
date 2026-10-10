from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import RequestScope, authorize_request
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.pricing.bands import TariffBandsError
from src.modules.pricing.creation import tao_bieu_gia
from src.modules.pricing.schemas import TariffCreateRequest, TariffResponse
from src.modules.pricing.service import (
    TariffDuplicateDateError,
    TariffEffectiveDateError,
    TariffNotFoundError,
)
from src.modules.stations.exceptions import StationOwnershipDeniedError
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/owner/stations",
    tags=["owner-tariffs"],
    route_class=PolicyRoute,
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "/{station_id}/tariffs",
    response_model=TariffResponse,
    status_code=201,
    responses={
        401: {"description": "Chưa đăng nhập"},
        403: {"description": "Không có quyền hoặc trạm thuộc chủ khác"},
        404: {"description": "Không tìm thấy trạm"},
        409: {"description": "Trùng ngày hiệu lực biểu giá"},
    },
)
@user_policy("owner.tariff.manage", "owned", "station_owner")
async def create_tariff(
    station_id: UUID,
    request: TariffCreateRequest,
    scope: RequestScope,
    db: Database,
) -> TariffResponse:
    try:
        response = await tao_bieu_gia(
            db,
            scope=scope,
            station_id=station_id,
            effective_from=request.effective_from,
            idle_rate_vnd_per_minute=request.idle_rate_vnd_per_minute,
            grace_minutes=request.grace_minutes,
            bands=request.band_inputs(),
        )
        await db.commit()
        return response
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    except TariffNotFoundError as error:
        raise HTTPException(404, "resource_not_found") from error
    except TariffDuplicateDateError as error:
        raise HTTPException(409, "tariff_duplicate_date") from error
    except TariffEffectiveDateError as error:
        raise HTTPException(
            422,
            [
                {
                    "loc": ["body", "effective_from"],
                    "msg": str(error),
                    "type": "value_error",
                }
            ],
        ) from error
    except TariffBandsError as error:
        raise HTTPException(
            422,
            [
                {
                    "loc": ["body", "bands"],
                    "type": issue.code,
                    "msg": issue.message,
                    "input_indices": list(issue.input_indices),
                    "start_min": issue.start_min,
                    "end_min": issue.end_min,
                }
                for issue in error.issues
            ],
        ) from error
