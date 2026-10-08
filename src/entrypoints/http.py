from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.driver_router import router as driver_charging_router
from src.modules.charging.router import router as charging_router
from src.modules.identity.admin_audit_router import router as admin_audit_router
from src.modules.identity.admin_router import router as admin_accounts_router
from src.modules.identity.authorization import AccessPolicy, access_policy
from src.modules.identity.policy_routing import PolicyRoute, require_policy_declaration
from src.modules.identity.router import router as identity_router
from src.modules.identity.scoped_routes import scoped_routes
from src.modules.ocpp.admin_health_router import router as health_router
from src.modules.ocpp.control_router import router as control_router
from src.modules.ocpp.lifecycle import ocpp_lifespan
from src.modules.ocpp.monitor_router import router as monitor_router
from src.modules.ocpp.router import router as ocpp_router
from src.modules.pricing.router import router as tariff_router
from src.modules.stations.charge_points_router import router as charge_points_router
from src.modules.stations.discovery_router import router as discovery_router
from src.modules.stations.photo_router import router as station_photo_router
from src.modules.stations.router import router as stations_router
from src.modules.wallet.admin_router import router as admin_wallet_router
from src.modules.wallet.driver_router import router as driver_wallet_router
from src.platform.database.session import get_db_session

app = FastAPI(
    title="CSMS",
    lifespan=ocpp_lifespan,
    dependencies=[Depends(require_policy_declaration)],
)
app.router.route_class = PolicyRoute
for documentation_route in app.routes:
    access_policy(AccessPolicy("public", note="Generated API documentation"))(
        cast(Any, documentation_route).endpoint
    )
app.include_router(identity_router)
app.include_router(admin_accounts_router)
app.include_router(admin_audit_router)
app.include_router(stations_router)
app.include_router(tariff_router)
app.include_router(station_photo_router)
app.include_router(charge_points_router)
# S-06: serve the OCPP WebSocket endpoint from the existing ASGI application.
app.include_router(ocpp_router)
app.include_router(monitor_router)
app.include_router(discovery_router)
app.include_router(charging_router)
app.include_router(driver_charging_router)
app.include_router(driver_wallet_router)
app.include_router(admin_wallet_router)
app.include_router(control_router)
app.include_router(health_router)
app.include_router(
    scoped_routes(
        [
            stations_router,
            station_photo_router,
            charge_points_router,
            charging_router,
            monitor_router,
        ]
    )
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


@app.get("/")
@access_policy(AccessPolicy("public", note="S-01 application entry"))
async def root() -> dict[str, str]:
    return {"status": "ok", "app": "CSMS"}


@app.get("/health/live")
@access_policy(AccessPolicy("public", note="Infrastructure liveness"))
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
@access_policy(AccessPolicy("public", note="Infrastructure readiness"))
async def health_ready(session: DatabaseSession) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from error

    return {"status": "ready"}
