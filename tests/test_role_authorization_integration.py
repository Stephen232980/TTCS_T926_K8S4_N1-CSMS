from uuid import uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from src.modules.identity.authorization import CurrentActor, allow_roles
from src.modules.identity.dependencies import authorize_request, get_current_actor


@pytest.fixture
def authorization_app() -> FastAPI:
    app = FastAPI()
    router = APIRouter(
        prefix="/protected",
        dependencies=[Depends(authorize_request)],
    )

    @router.get("/without-policy")
    async def route_without_policy() -> dict[str, str]:
        return {"status": "should-not-run"}

    @router.get("/admin")
    @allow_roles("admin")
    async def admin_route() -> dict[str, str]:
        return {"status": "allowed"}

    app.include_router(router)
    return app


def test_unauthenticated_request_returns_401(
    authorization_app: FastAPI,
) -> None:
    with TestClient(authorization_app) as client:
        response = client.get("/protected/admin")

    assert response.status_code == 401


def test_admin_cannot_call_route_without_policy(
    authorization_app: FastAPI,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"admin"}),
    )
    authorization_app.dependency_overrides[get_current_actor] = lambda: actor

    with TestClient(authorization_app) as client:
        response = client.get("/protected/without-policy")

    assert response.status_code == 403
    assert response.json() == {"detail": "Không có quyền truy cập"}


def test_wrong_role_returns_403(
    authorization_app: FastAPI,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )
    authorization_app.dependency_overrides[get_current_actor] = lambda: actor

    with TestClient(authorization_app) as client:
        response = client.get("/protected/admin")

    assert response.status_code == 403


def test_matching_role_reaches_handler(
    authorization_app: FastAPI,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"admin"}),
    )
    authorization_app.dependency_overrides[get_current_actor] = lambda: actor

    with TestClient(authorization_app) as client:
        response = client.get("/protected/admin")

    assert response.status_code == 200
    assert response.json() == {"status": "allowed"}
