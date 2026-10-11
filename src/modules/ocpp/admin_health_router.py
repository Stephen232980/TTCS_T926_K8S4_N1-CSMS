from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.admin_router import AdminAccountRoute
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import authorize_request
from src.modules.ocpp.admin_health_models import SystemHealthSample
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/system-health",
    tags=["admin-health"],
    dependencies=[Depends(authorize_request)],
    route_class=AdminAccountRoute,
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


def health_now() -> datetime:
    return datetime.now(UTC)


Clock = Annotated[datetime, Depends(health_now)]


class HealthMetrics(BaseModel):
    online_charge_points: int
    registered_charge_points: int
    running_sessions: int
    error_messages_5m: int | None
    error_messages_observed_5m: int
    response_latency_ms: float | None
    response_count_5m: int
    window_complete: bool


def metrics(sample: SystemHealthSample) -> HealthMetrics:
    return HealthMetrics(
        **{key: getattr(sample, key) for key in HealthMetrics.model_fields}
    )


class HealthSnapshot(BaseModel):
    collected_at: datetime
    window_start: datetime
    window_end: datetime
    metrics: HealthMetrics


class HealthResponse(BaseModel):
    generated_at: datetime
    refresh_after_seconds: int = 30
    stale_after_seconds: int = 90
    status: Literal["current", "stale", "no_data"]
    snapshot: HealthSnapshot | None


@router.get("", response_model=HealthResponse)
@user_policy("admin.health.read", "all", "admin")
async def current_health(db: Database, now: Clock) -> HealthResponse:
    sample = await db.scalar(
        select(SystemHealthSample)
        .where(SystemHealthSample.collected_at <= now)
        .order_by(SystemHealthSample.timestamp.desc())
        .limit(1)
    )
    return HealthResponse(
        generated_at=now,
        status="no_data"
        if sample is None
        else "stale"
        if now - sample.collected_at > timedelta(seconds=90)
        else "current",
        snapshot=HealthSnapshot(
            collected_at=sample.collected_at,
            window_start=sample.timestamp - timedelta(minutes=5),
            window_end=sample.timestamp,
            metrics=metrics(sample),
        )
        if sample
        else None,
    )


class HealthHistoryPoint(BaseModel):
    bucket_start: datetime
    measured_at: datetime | None
    metrics: HealthMetrics | None


class HealthHistoryResponse(BaseModel):
    from_at: datetime
    to_at: datetime
    resolution_seconds: int
    aggregation: Literal["latest_observation"] = "latest_observation"
    available_since: datetime | None
    points: list[HealthHistoryPoint]


@router.get("/history", response_model=HealthHistoryResponse)
@user_policy("admin.health.read", "all", "admin")
async def health_history(
    db: Database,
    now: Clock,
    resolution_seconds: Annotated[int, Query(ge=30, le=3600)] = 3600,
) -> HealthHistoryResponse:
    if resolution_seconds not in {30, 60, 300, 900, 1800, 3600}:
        raise HTTPException(422, "Độ phân giải không được hỗ trợ")

    def align(value: datetime) -> datetime:
        seconds = int(value.timestamp())
        return datetime.fromtimestamp(
            seconds // resolution_seconds * resolution_seconds, UTC
        )

    end = align(now)
    start = end - timedelta(hours=24)
    samples = await db.scalars(
        select(SystemHealthSample)
        .where(
            SystemHealthSample.timestamp >= start,
            SystemHealthSample.collected_at <= now,
            SystemHealthSample.timestamp <= now,
        )
        .order_by(SystemHealthSample.timestamp)
    )
    latest = {align(sample.timestamp): sample for sample in samples}
    available_since = await db.scalar(select(func.min(SystemHealthSample.collected_at)))
    points: list[HealthHistoryPoint] = []
    timestamp = start
    while timestamp <= end:
        sample = latest.get(timestamp)
        points.append(
            HealthHistoryPoint(
                bucket_start=timestamp,
                measured_at=sample.collected_at if sample else None,
                metrics=metrics(sample) if sample else None,
            )
        )
        timestamp += timedelta(seconds=resolution_seconds)
    return HealthHistoryResponse(
        from_at=start,
        to_at=now,
        resolution_seconds=resolution_seconds,
        available_since=available_since,
        points=points,
    )
