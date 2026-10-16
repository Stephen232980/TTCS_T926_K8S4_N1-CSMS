from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import RequestScope, authorize_request
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.reporting.schemas import (
    PeriodType,
    RevenueReportQuery,
    RevenueReportResponse,
)
from src.modules.reporting.service import export_revenue_report_csv, get_revenue_report
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    tags=["reporting"],
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


@router.get(
    "/api/v1/owner/reports/revenue",
    response_model=RevenueReportResponse,
)
@user_policy("owner.reports.revenue", "owned", "station_owner")
async def get_owner_revenue_report(
    scope: RequestScope,
    db: Database,
    period: Annotated[PeriodType, Query()] = "month",
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    station_id: Annotated[UUID | None, Query()] = None,
    charge_point_id: Annotated[UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RevenueReportResponse:
    query = RevenueReportQuery(
        period=period,
        date_from=date_from,
        date_to=date_to,
        station_id=station_id,
        charge_point_id=charge_point_id,
        page=page,
        page_size=page_size,
    )
    return await get_revenue_report(
        db, query, owner_id=scope.owner_id or scope.actor_id
    )


@router.get(
    "/api/v1/owner/reports/revenue/export",
)
@user_policy("owner.reports.revenue", "owned", "station_owner")
async def export_owner_revenue_report(
    scope: RequestScope,
    db: Database,
    period: Annotated[PeriodType, Query()] = "month",
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    station_id: Annotated[UUID | None, Query()] = None,
    charge_point_id: Annotated[UUID | None, Query()] = None,
) -> StreamingResponse:
    query = RevenueReportQuery(
        period=period,
        date_from=date_from,
        date_to=date_to,
        station_id=station_id,
        charge_point_id=charge_point_id,
        page=1,
        page_size=100,
    )
    return await export_revenue_report_csv(
        db, query, owner_id=scope.owner_id or scope.actor_id
    )


@router.get(
    "/api/v1/accounting/reports/revenue",
    response_model=RevenueReportResponse,
)
@user_policy("accounting.reports.revenue", "all", "accountant")
async def get_accounting_revenue_report(
    db: Database,
    period: Annotated[PeriodType, Query()] = "month",
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    station_id: Annotated[UUID | None, Query()] = None,
    charge_point_id: Annotated[UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RevenueReportResponse:
    query = RevenueReportQuery(
        period=period,
        date_from=date_from,
        date_to=date_to,
        station_id=station_id,
        charge_point_id=charge_point_id,
        page=page,
        page_size=page_size,
    )
    return await get_revenue_report(db, query, owner_id=None)


@router.get(
    "/api/v1/accounting/reports/revenue/export",
)
@user_policy("accounting.reports.revenue", "all", "accountant")
async def export_accounting_revenue_report(
    db: Database,
    period: Annotated[PeriodType, Query()] = "month",
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    station_id: Annotated[UUID | None, Query()] = None,
    charge_point_id: Annotated[UUID | None, Query()] = None,
) -> StreamingResponse:
    query = RevenueReportQuery(
        period=period,
        date_from=date_from,
        date_to=date_to,
        station_id=station_id,
        charge_point_id=charge_point_id,
        page=1,
        page_size=100,
    )
    return await export_revenue_report_csv(db, query, owner_id=None)
