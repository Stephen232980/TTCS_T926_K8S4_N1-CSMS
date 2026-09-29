import asyncio
import selectors

from fastapi.testclient import TestClient

from src.entrypoints.http import app

client = TestClient(
    app,
    backend_options={
        "loop_factory": lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    },
)


def test_root() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "CSMS"}


def test_health_live() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready() -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
