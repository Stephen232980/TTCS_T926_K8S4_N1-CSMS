import csv
from itertools import combinations
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.entrypoints.http import app
from src.modules.identity.authorization import (
    AccessPolicy,
    CurrentActor,
    access_policy,
    enforce_role_policy,
    get_access_policy,
    user_policy,
)
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.identity.role_assignment import KNOWN_ROLES, validate_role_assignment
from src.modules.identity.route_inventory import registered_routes, route_inventory


def test_every_registered_http_and_websocket_route_has_exactly_one_valid_policy() -> (
    None
):
    keys = []
    for route, path in registered_routes(app.routes):
        policy = get_access_policy(route.endpoint)
        assert policy is not None, path
        assert policy.kind in {"user", "public", "device", "webhook"}, path
        if policy.kind == "user":
            assert policy.permission and policy.scope and policy.roles <= KNOWN_ROLES, (
                path
            )
            assert isinstance(route, PolicyRoute), path
        else:
            assert not policy.permission and not policy.scope and not policy.roles, path
        if not getattr(route, "methods", None):
            assert policy.kind == "device", path
        for method in getattr(route, "methods", None) or {"WEBSOCKET"}:
            keys.append((method, path))
    assert len(keys) == len(set(keys)), "Duplicate route registration"
    rows = route_inventory(app.routes)
    assert len(rows) == len(keys)
    assert not any(r["kind"] == "MISSING" for r in rows)
    with Path("docs/ROUTE_ACCESS_INVENTORY.csv").open(
        encoding="utf-8", newline=""
    ) as snapshot:
        assert list(csv.DictReader(snapshot)) == rows


def test_every_user_endpoint_against_all_role_combinations() -> None:
    roles = sorted(KNOWN_ROLES)
    for route, path in registered_routes(app.routes):
        policy = get_access_policy(route.endpoint)
        if policy is None or policy.kind != "user":
            continue
        for count in range(6):
            for combo in combinations(roles, count):
                actor = CurrentActor(uuid4(), frozenset(combo))
                if policy.roles & actor.roles:
                    enforce_role_policy(route.endpoint, actor)
                else:
                    with pytest.raises(HTTPException) as error:
                        enforce_role_policy(route.endpoint, actor)
                    assert error.value.status_code == 403, (path, combo)


def test_missing_policy_denied_even_without_router_authorization_dependency() -> None:
    local = FastAPI()
    router = APIRouter(route_class=PolicyRoute)

    @router.get("/missing")
    async def missing() -> dict[str, str]:
        return {"result": "must not execute"}

    local.include_router(router)
    with TestClient(local) as client:
        assert client.get("/missing").status_code == 403


def test_policy_cannot_be_overwritten_or_mix_authentication_types() -> None:
    @user_policy("owner.test", "owned", "station_owner")
    def handler() -> None:
        pass

    with pytest.raises(ValueError, match="exactly one"):
        access_policy(AccessPolicy("public"))(handler)
    with pytest.raises(ValueError, match="Non-user"):
        access_policy(AccessPolicy("webhook", permission="admin.test"))


@pytest.mark.parametrize(
    "roles", [["admin", "accountant"], ["station_owner", "driver"]]
)
def test_empty_forbidden_configuration_allows_unrestricted_combinations(
    roles: list[str],
) -> None:
    validate_role_assignment(roles)


@pytest.mark.parametrize("roles", [["admin", "accountant"], ["accountant", "admin"]])
def test_forbidden_pair_validation_is_order_independent(roles: list[str]) -> None:
    with pytest.raises(HTTPException) as error:
        validate_role_assignment(
            roles, forbidden_pairs=[frozenset({"admin", "accountant"})]
        )
    assert error.value.status_code == 422


@pytest.mark.parametrize("roles", [[], ["unknown"], ["driver", "driver"]])
def test_invalid_assignment_is_rejected(roles: list[str]) -> None:
    with pytest.raises(HTTPException):
        validate_role_assignment(roles)
