"""Accounting reconciliation router for S-53."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounting.models import ReconciliationRun
from src.modules.accounting.schemas import (
    IssueSeverity,
    ReconciliationIssueResponse,
    ReconciliationIssuesListResponse,
    ReconciliationRunCreateRequest,
    ReconciliationRunListResponse,
    ReconciliationRunResponse,
)
from src.modules.accounting.service import (
    execute_reconciliation_run,
    export_reconciliation_issues_csv,
    get_reconciliation_issues,
    get_reconciliation_run,
    list_reconciliation_runs,
)
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import RequestScope, authorize_request
from src.modules.identity.policy_routing import PolicyRoute
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/accounting/reconciliation-runs",
    tags=["accounting-reconciliation"],
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


def present_run(run: ReconciliationRun) -> ReconciliationRunResponse:
    return ReconciliationRunResponse(
        id=run.id,
        period_type=run.period_type,
        date_from=run.date_from,
        date_to=run.date_to,
        station_id=run.station_id,
        cutoff_at=run.cutoff_at,
        created_at=run.created_at,
        created_by=run.created_by,
        status=run.status,
        total_sessions=run.total_sessions,
        matched_sessions=run.matched_sessions,
        mismatch_sessions=run.mismatch_sessions,
        missing_data_sessions=run.missing_data_sessions,
        total_meter_kwh=str(run.total_meter_kwh),
        total_billed_kwh=str(run.total_billed_kwh),
        kwh_discrepancy=str(run.kwh_discrepancy),
        total_billed_vnd=str(run.total_billed_vnd),
        total_recomputed_vnd=str(run.total_recomputed_vnd),
        total_debited_vnd=str(run.total_debited_vnd),
        money_discrepancy_vnd=str(run.money_discrepancy_vnd),
        summary_counts=run.summary_counts,
        algorithm_version=run.algorithm_version,
    )


@router.post(
    "",
    response_model=ReconciliationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
@user_policy("accounting.reconciliation.manage", "all", "accountant")
async def create_run(
    request: ReconciliationRunCreateRequest,
    db: Database,
    scope: RequestScope,
) -> ReconciliationRunResponse:
    run = await execute_reconciliation_run(
        db, request, actor_id=scope.actor_id or scope.owner_id
    )
    await db.commit()
    await db.refresh(run)
    return present_run(run)


@router.get(
    "",
    response_model=ReconciliationRunListResponse,
)
@user_policy("accounting.reconciliation.read", "all", "accountant")
async def list_runs(
    db: Database,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    station_id: Annotated[UUID | None, Query()] = None,
) -> ReconciliationRunListResponse:
    items, total = await list_reconciliation_runs(
        db, page=page, page_size=page_size, station_id=station_id
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return ReconciliationRunListResponse(
        items=[present_run(r) for r in items],
        total=total,
        page=page,
        total_pages=total_pages,
    )


@router.get(
    "/{run_id}",
    response_model=ReconciliationRunResponse,
)
@user_policy("accounting.reconciliation.read", "all", "accountant")
async def get_run_by_id(
    run_id: UUID,
    db: Database,
) -> ReconciliationRunResponse:
    run = await get_reconciliation_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đợt đối soát",
        )
    return present_run(run)


@router.get(
    "/{run_id}/issues",
    response_model=ReconciliationIssuesListResponse,
)
@user_policy("accounting.reconciliation.read", "all", "accountant")
async def get_run_issues(
    run_id: UUID,
    db: Database,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    severity: Annotated[IssueSeverity | None, Query()] = None,
    issue_type: Annotated[str | None, Query()] = None,
) -> ReconciliationIssuesListResponse:
    run = await get_reconciliation_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đợt đối soát",
        )
    items, total = await get_reconciliation_issues(
        db,
        run_id=run_id,
        page=page,
        page_size=page_size,
        severity=severity,
        issue_type=issue_type,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return ReconciliationIssuesListResponse(
        items=[ReconciliationIssueResponse(**item) for item in items],
        total=total,
        page=page,
        total_pages=total_pages,
    )


@router.get(
    "/{run_id}/issues/export",
)
@user_policy("accounting.reconciliation.read", "all", "accountant")
async def export_run_issues(
    run_id: UUID,
    db: Database,
    severity: Annotated[IssueSeverity | None, Query()] = None,
    issue_type: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    return await export_reconciliation_issues_csv(
        db,
        run_id=run_id,
        severity=severity,
        issue_type=issue_type,
    )
