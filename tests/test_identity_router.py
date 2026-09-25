import asyncio
import selectors
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

import src.modules.identity.router as router_module
from src.entrypoints.http import app
from src.modules.identity.service import (
    AuthService,
    InvalidCredentialsError,
    LoginLockedError,
    LoginResult,
)
from src.platform.database.session import get_db_session


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_db_session] = lambda: object()

    with TestClient(
        app,
        backend_options={
            "loop_factory": lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            )
        },
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def auth_service(monkeypatch: pytest.MonkeyPatch) -> Mock:
    service = Mock(spec=AuthService)
    service.login = AsyncMock()
    service.logout = AsyncMock()

    monkeypatch.setattr(
        router_module,
        "build_auth_service",
        lambda _db_session: service,
    )
    return service


def test_login_returns_cookie(
    client: TestClient,
    auth_service: Mock,
) -> None:
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    auth_service.login.return_value = LoginResult(
        token="session-token-goc",
        expires_at=expires_at,
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "mat-khau-dung",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "authenticated"}

    set_cookie = response.headers["set-cookie"]
    assert "session=session-token-goc" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Max-Age=" in set_cookie

    auth_service.login.assert_awaited_once_with(
        email="owner@example.com",
        password="mat-khau-dung",
        ip_address="testclient",
    )


def test_login_returns_generic_error_for_invalid_credentials(
    client: TestClient,
    auth_service: Mock,
) -> None:
    auth_service.login.side_effect = InvalidCredentialsError()

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "missing@example.com",
            "password": "mat-khau-sai",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Email hoặc mật khẩu không đúng"}
    assert "set-cookie" not in response.headers


def test_login_returns_locked_error(
    client: TestClient,
    auth_service: Mock,
) -> None:
    auth_service.login.side_effect = LoginLockedError()

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "mat-khau-dung",
        },
    )

    assert response.status_code == 423
    assert response.json() == {"detail": "Đăng nhập tạm thời bị khóa"}


def test_login_rejects_invalid_email_before_calling_service(
    client: TestClient,
    auth_service: Mock,
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "email-khong-hop-le",
            "password": "mat-khau",
        },
    )

    assert response.status_code == 422
    auth_service.login.assert_not_awaited()


def test_secure_cookie_can_be_enabled(
    client: TestClient,
    auth_service: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        router_module.settings,
        "auth_cookie_secure",
        True,
    )
    auth_service.login.return_value = LoginResult(
        token="secure-session-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "mat-khau-dung",
        },
    )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_logout_revokes_session_and_deletes_cookie(
    client: TestClient,
    auth_service: Mock,
) -> None:
    client.cookies.set("session", "session-token-can-thu-hoi")

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert response.content == b""
    auth_service.logout.assert_awaited_once_with("session-token-can-thu-hoi")

    set_cookie = response.headers["set-cookie"]
    assert "session=" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_logout_without_cookie_is_idempotent(
    client: TestClient,
    auth_service: Mock,
) -> None:
    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    auth_service.logout.assert_awaited_once_with(None)
