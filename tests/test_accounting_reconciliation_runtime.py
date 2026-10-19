from httpx import ASGITransport, AsyncClient

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from tests.test_ocpp_control import db_session as isolated_session
from tests.test_t82_driver_invoice import sample

db_session = isolated_session


async def test_real_postgres_run_detail_and_issues_csv(db_session):
    charging, driver = await sample(db_session)
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        driver.id, frozenset({"accountant"})
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/accounting/reconciliation-runs",
            json={"date_from": "2026-10-01", "date_to": "2026-10-31"},
        )
        assert response.status_code == 201, response.text
        rid = response.json()["id"]
        detail = await client.get(f"/api/v1/accounting/reconciliation-runs/{rid}")
        assert detail.status_code == 200
        issues = await client.get(
            f"/api/v1/accounting/reconciliation-runs/{rid}/issues"
        )
        assert issues.status_code == 200 and issues.json()["items"]
        exported = await client.get(
            f"/api/v1/accounting/reconciliation-runs/{rid}/issues/export"
        )
        assert exported.status_code == 200
        assert "text/csv" in exported.headers["content-type"]
        assert "run_id" in exported.text and rid in exported.text
        assert str(charging.id) in exported.text
