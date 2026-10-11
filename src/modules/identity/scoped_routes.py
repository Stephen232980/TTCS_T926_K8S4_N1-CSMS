"""Explicit routes sharing handlers, with server-selected scopes and policies."""

import inspect
from collections.abc import Callable, Coroutine, Iterable
from functools import wraps
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute

from src.modules.identity.authorization import (
    AccessPolicy,
    access_policy,
    get_access_policy,
)
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.stations.schemas import StationListResponse, StationResponse

# Deliberate global read grants. New owner GETs never gain global access implicitly.
GLOBAL_READ_PERMISSIONS = frozenset(
    {
        "owner.stations.list_stations",
        "owner.stations.get_station",
        "owner.stations.list_charge_points",
        "owner.photos.get_photo",
        "owner.charging.cards",
        "owner.charging.sessions",
        "owner.charging.samples",
        "owner.charging.session_events",
        "owner.charging.pending_messages",
        "owner.monitor.read",
    }
)
ACCOUNTING_READ_PERMISSIONS = frozenset(
    {
        "owner.charging.sessions",
        "owner.charging.samples",
        "owner.charging.session_events",
    }
)
OPS_CARD_WRITE_PERMISSIONS = frozenset(
    {"owner.charging.create_card", "owner.charging.update_card"}
)


def scoped_handler(
    handler: Callable[..., Coroutine[Any, Any, Any]], policy: AccessPolicy, area: str
) -> Callable[..., Coroutine[Any, Any, Any]]:
    @wraps(handler, updated=())
    async def endpoint(*args: Any, **kwargs: Any) -> Any:
        result = await handler(*args, **kwargs)
        # Links returned by an area must use that area's authorization as well.
        stations = (
            result.items
            if isinstance(result, StationListResponse)
            else [result]
            if isinstance(result, StationResponse)
            else []
        )
        for station in stations:
            if station.photo_url:
                station.photo_url = station.photo_url.replace(
                    "/api/v1/stations/", f"/api/v1/{area}/stations/", 1
                )
        return result

    # Resolve annotations in the original handler's module before sharing it.
    endpoint.__dict__["__signature__"] = inspect.signature(handler, eval_str=True)
    return access_policy(policy)(endpoint)


def scoped_routes(routers: Iterable[APIRouter]) -> APIRouter:
    result = APIRouter(route_class=PolicyRoute)
    for router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            policy = get_access_policy(route.endpoint)
            if policy is None or policy.scope != "owned" or policy.permission is None:
                continue
            variants = [("owner", policy)]
            if (
                route.methods == {"GET"}
                and policy.permission in GLOBAL_READ_PERMISSIONS
            ):
                variants.extend(
                    [
                        (
                            "ops",
                            AccessPolicy(
                                "user",
                                policy.permission.replace("owner.", "ops."),
                                "all",
                                frozenset({"operator"}),
                            ),
                        ),
                        (
                            "admin",
                            AccessPolicy(
                                "user",
                                policy.permission.replace("owner.", "admin."),
                                "all",
                                frozenset({"admin"}),
                            ),
                        ),
                    ]
                )
                if policy.permission in ACCOUNTING_READ_PERMISSIONS:
                    variants.append(
                        (
                            "accounting",
                            AccessPolicy(
                                "user",
                                "accounting.sessions.read",
                                "all",
                                frozenset({"accountant"}),
                            ),
                        )
                    )
            # Card administration was available to operators; preserve via explicit ops routes.
            elif policy.permission in OPS_CARD_WRITE_PERMISSIONS:
                variants.append(
                    (
                        "ops",
                        AccessPolicy(
                            "user", "ops.cards.manage", "all", frozenset({"operator"})
                        ),
                    )
                )
            for area, access in variants:
                result.add_api_route(
                    route.path.replace("/api/v1/", f"/api/v1/{area}/", 1),
                    scoped_handler(route.endpoint, access, area),
                    methods=sorted(route.methods or []),
                    response_model=route.response_model,
                    status_code=route.status_code,
                    response_class=route.response_class,
                    name=f"{area}_{route.name}",
                    tags=[area],
                )
    return result
