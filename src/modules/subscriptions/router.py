"""Owner plan management and driver monthly-subscription routes."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    CurrentActorDependency,
    RequestScope,
    authorize_request,
)
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.pricing.bands import BandInput, TariffBandsError, kiem_khung_gio
from src.modules.pricing.schemas import TariffBandCreateRequest
from src.modules.stations.exceptions import StationOwnershipDeniedError
from src.modules.stations.models import Station
from src.modules.stations.repository import StationRepository
from src.modules.subscriptions.models import (
    DriverSubscription,
    SubscriptionPlan,
    SubscriptionPlanBand,
)
from src.modules.subscriptions.schemas import (
    DriverSubscriptionResponse,
    SubscriptionBandResponse,
    SubscriptionPlanCreate,
    SubscriptionPlanResponse,
)
from src.modules.subscriptions.service import (
    SubscriptionConflictError,
    SubscriptionFundsError,
    SubscriptionNotFoundError,
    dang_ky,
    huy_dang_ky,
    lay_goi,
    tao_goi,
)
from src.modules.wallet.exceptions import WalletLockedError
from src.platform.database.session import get_db_session

owner_router = APIRouter(
    prefix="/api/v1/owner/stations",
    tags=["owner-subscriptions"],
    route_class=PolicyRoute,
    dependencies=[Depends(authorize_request)],
)
driver_router = APIRouter(
    prefix="/api/v1/driver/subscriptions",
    tags=["driver-subscriptions"],
    route_class=PolicyRoute,
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


async def _plan_response(
    db: AsyncSession, plan: SubscriptionPlan
) -> SubscriptionPlanResponse:
    bands = await db.scalars(
        select(SubscriptionPlanBand)
        .where(SubscriptionPlanBand.plan_id == plan.id)
        .order_by(SubscriptionPlanBand.start_min)
    )
    station_name = await db.scalar(
        select(Station.name).where(Station.id == plan.station_id)
    )
    if station_name is None:
        raise SubscriptionNotFoundError("Subscription station does not exist")
    return SubscriptionPlanResponse(
        id=plan.id,
        station_id=plan.station_id,
        station_name=station_name,
        name=plan.name,
        monthly_fee_vnd=str(plan.monthly_fee_vnd),
        active=plan.active,
        bands=[
            SubscriptionBandResponse(
                start_min=band.start_min,
                end_min=band.end_min,
                energy_rate_vnd_per_kwh=str(band.energy_rate_vnd_per_kwh),
                label=band.label,
            )
            for band in bands
        ],
    )


async def _subscription_response(
    db: AsyncSession, subscription: DriverSubscription
) -> DriverSubscriptionResponse:
    plan = await lay_goi(db, subscription.plan_id)
    station_name = await db.scalar(
        select(Station.name).where(Station.id == subscription.station_id)
    )
    if station_name is None:
        raise SubscriptionNotFoundError("Subscription station does not exist")
    return DriverSubscriptionResponse(
        id=subscription.id,
        station_id=subscription.station_id,
        station_name=station_name,
        plan_id=subscription.plan_id,
        plan_name=plan.name,
        monthly_fee_vnd=str(plan.monthly_fee_vnd),
        status=subscription.status,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        next_billing_at=(
            subscription.next_billing_at if subscription.status != "cancelled" else None
        ),
    )


def _normalized_bands(
    bands: list[TariffBandCreateRequest],
) -> list[tuple[int, int, int, str]]:
    try:
        normalized = kiem_khung_gio(
            [
                BandInput(
                    band.start_min,
                    band.end_min,
                    band.energy_rate_vnd_per_kwh,
                    band.label,
                )
                for band in bands
            ]
        )
    except TariffBandsError as error:
        raise HTTPException(
            422,
            [
                {
                    "type": issue.code,
                    "msg": issue.message,
                    "input_indices": list(issue.input_indices),
                    "start_min": issue.start_min,
                    "end_min": issue.end_min,
                }
                for issue in error.issues
            ],
        ) from error
    return [
        (
            band.start_min,
            band.end_min,
            band.energy_rate_vnd_per_kwh,
            band.label.strip()
            or f"{band.start_min // 60:02d}:{band.start_min % 60:02d}-"
            f"{band.end_min // 60:02d}:{band.end_min % 60:02d}",
        )
        for band in normalized
    ]


@owner_router.post(
    "/{station_id}/subscription-plans",
    response_model=SubscriptionPlanResponse,
    status_code=201,
)
@user_policy("owner.subscription.manage", "owned", "station_owner")
async def create_plan(
    station_id: UUID,
    request: SubscriptionPlanCreate,
    scope: RequestScope,
    db: Database,
) -> SubscriptionPlanResponse:
    try:
        station = await StationRepository(db).get_station_by_id(station_id, scope)
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    if station is None:
        raise HTTPException(404, "resource_not_found")
    plan = await tao_goi(
        db,
        station_id=station.id,
        name=request.name,
        monthly_fee_vnd=request.monthly_fee_vnd,
        bands=_normalized_bands(request.bands),
    )
    result = await _plan_response(db, plan)
    await db.commit()
    return result


@owner_router.get(
    "/{station_id}/subscription-plans",
    response_model=list[SubscriptionPlanResponse],
)
@user_policy("owner.subscription.manage", "owned", "station_owner")
async def list_owner_plans(
    station_id: UUID, scope: RequestScope, db: Database
) -> list[SubscriptionPlanResponse]:
    try:
        station = await StationRepository(db).get_station_by_id(station_id, scope)
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    if station is None:
        raise HTTPException(404, "resource_not_found")
    plans = await db.scalars(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.station_id == station_id)
        .order_by(SubscriptionPlan.created_at.desc())
    )
    return [await _plan_response(db, plan) for plan in plans]


@owner_router.post(
    "/{station_id}/subscription-plans/{plan_id}/deactivate",
    response_model=SubscriptionPlanResponse,
)
@user_policy("owner.subscription.manage", "owned", "station_owner")
async def deactivate_plan(
    station_id: UUID,
    plan_id: UUID,
    scope: RequestScope,
    db: Database,
) -> SubscriptionPlanResponse:
    try:
        station = await StationRepository(db).get_station_by_id(station_id, scope)
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    if station is None:
        raise HTTPException(404, "resource_not_found")
    plan = await db.scalar(
        select(SubscriptionPlan)
        .where(
            SubscriptionPlan.id == plan_id,
            SubscriptionPlan.station_id == station_id,
        )
        .with_for_update()
    )
    if plan is None:
        raise HTTPException(404, "resource_not_found")
    plan.active = False
    result = await _plan_response(db, plan)
    await db.commit()
    return result


@driver_router.get("/plans", response_model=list[SubscriptionPlanResponse])
@user_policy("driver.subscription.read", "own_wallet", "driver")
async def list_available_plans(
    db: Database,
    station_id: Annotated[UUID | None, Query()] = None,
) -> list[SubscriptionPlanResponse]:
    query = select(SubscriptionPlan).where(SubscriptionPlan.active.is_(True))
    if station_id is not None:
        query = query.where(SubscriptionPlan.station_id == station_id)
    plans = await db.scalars(
        query.order_by(SubscriptionPlan.station_id, SubscriptionPlan.name)
    )
    return [await _plan_response(db, plan) for plan in plans]


@driver_router.get("", response_model=list[DriverSubscriptionResponse])
@user_policy("driver.subscription.read", "own_wallet", "driver")
async def list_my_subscriptions(
    actor: CurrentActorDependency,
    db: Database,
    response: Response,
) -> list[DriverSubscriptionResponse]:
    now = datetime.now(UTC)
    rows = await db.scalars(
        select(DriverSubscription)
        .where(
            DriverSubscription.driver_id == actor.user_id,
            or_(
                DriverSubscription.status.in_(("active", "past_due")),
                DriverSubscription.current_period_end > now,
            ),
        )
        .order_by(DriverSubscription.current_period_end.desc())
    )
    response.headers["Cache-Control"] = "no-store"
    return [await _subscription_response(db, row) for row in rows]


@driver_router.post(
    "/plans/{plan_id}",
    response_model=DriverSubscriptionResponse,
    status_code=201,
    responses={402: {"description": "Không đủ số dư ví"}},
)
@user_policy("driver.subscription.manage", "own_wallet", "driver")
async def subscribe(
    plan_id: UUID, actor: CurrentActorDependency, db: Database
) -> DriverSubscriptionResponse:
    try:
        subscription = await dang_ky(db, driver_id=actor.user_id, plan_id=plan_id)
        result = await _subscription_response(db, subscription)
        await db.commit()
    except SubscriptionFundsError as error:
        await db.rollback()
        raise HTTPException(402, "insufficient_wallet_balance") from error
    except WalletLockedError as error:
        await db.rollback()
        raise HTTPException(409, "wallet_locked") from error
    except SubscriptionConflictError as error:
        await db.rollback()
        raise HTTPException(409, "subscription_already_active") from error
    except SubscriptionNotFoundError as error:
        await db.rollback()
        raise HTTPException(404, "subscription_plan_not_found") from error
    return result


@driver_router.delete(
    "/{subscription_id}",
    response_model=DriverSubscriptionResponse,
)
@user_policy("driver.subscription.manage", "own_wallet", "driver")
async def cancel_subscription(
    subscription_id: UUID,
    actor: CurrentActorDependency,
    db: Database,
) -> DriverSubscriptionResponse:
    try:
        subscription = await huy_dang_ky(
            db,
            driver_id=actor.user_id,
            subscription_id=subscription_id,
        )
        result = await _subscription_response(db, subscription)
        await db.commit()
    except SubscriptionNotFoundError as error:
        await db.rollback()
        raise HTTPException(404, "subscription_not_found") from error
    except SubscriptionConflictError as error:
        await db.rollback()
        raise HTTPException(409, "subscription_already_cancelled") from error
    return result
