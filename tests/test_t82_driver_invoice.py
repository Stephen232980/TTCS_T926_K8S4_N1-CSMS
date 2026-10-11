from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.entrypoints.http import app
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from tests.test_charging_sessions import setup
from tests.test_ocpp_control import db_session as isolated_session
from tests.test_tariff_schema import make_tariff

db_session = isolated_session


async def sample(db, *, review=False, invoice=True, total=3500, existing_driver=None):
    station, charger, connector, driver, *_ = await setup(db)
    driver = existing_driver or driver
    stamp = datetime(2026, 10, 10, 2, tzinfo=UTC)
    charging = ChargingSession(
        charge_point_id=charger.id,
        connector_id=connector.id,
        driver_id=driver.id,
        tag_tail="TEST",
        authorization_status="Accepted",
        started_at=stamp,
        ended_at=stamp + timedelta(hours=1),
        meter_start_wh=0,
        meter_stop_wh=1000,
        review_reasons=["meter_decreased"] if review else [],
    )
    db.add(charging)
    await db.flush()
    if invoice:
        tariff = await make_tariff(db)
        tariff.station_id = station.id
        saved = Invoice(
            session_id=charging.id,
            driver_id=driver.id,
            station_id=station.id,
            total_vnd=total,
            rounding_rule="Làm tròn từng dòng rồi cộng tổng",
        )
        db.add(saved)
        await db.flush()
        for kind, amount, rate, energy in [
            ("energy", total - 500, 3000, Decimal("1000.125")),
            ("idle", 500, 100, Decimal(0)),
        ]:
            db.add(
                InvoiceLine(
                    invoice_id=saved.id,
                    line_type=kind,
                    local_date=date(2026, 10, 10),
                    started_at=stamp + timedelta(minutes=55)
                    if kind == "idle"
                    else stamp,
                    ended_at=stamp + timedelta(hours=1),
                    energy_wh=energy,
                    rate_vnd=rate,
                    band_label="Ban ngày",
                    interpolated=True,
                    tariff_id=tariff.id,
                    amount_vnd=amount,
                )
            )
    await db.flush()
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=driver.id, roles=frozenset({"driver"})
    )
    return charging, driver


async def get(path):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


async def test_reads_saved_lines_and_bigint_without_float_loss(db_session):
    charging, _ = await sample(db_session, total=9007199254740993)
    response = await get(f"/api/v1/driver/charging/sessions/{charging.id}/invoice")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["total_vnd"] == "9007199254740993"
    assert {line["line_type"] for line in data["lines"]} == {"energy", "idle"}
    energy = next(line for line in data["lines"] if line["line_type"] == "energy")
    assert Decimal(energy["energy_kwh"]) == Decimal("1.000125")
    assert energy["rate_vnd"] == "3000"
    assert data["rounding_rule"]
    assert (
        await get(f"/api/v1/driver/charging/sessions/{charging.id}/invoice")
    ).json() == data


@pytest.mark.parametrize(
    "review,has_invoice,state",
    [
        (True, True, "needs_review"),
        (True, False, "needs_review"),
        (False, False, "pending"),
    ],
)
async def test_waiting_states_hide_money_and_lines(
    db_session, review, has_invoice, state
):
    charging, _ = await sample(db_session, review=review, invoice=has_invoice)
    response = await get(f"/api/v1/driver/charging/sessions/{charging.id}/invoice")
    data = response.json()
    assert data["status"] == state
    assert data["total_vnd"] is None and data["lines"] == []
    listing = (await get("/api/v1/driver/invoices")).json()
    assert listing["items"][0]["status"] == state
    assert listing["items"][0]["total_vnd"] is None


async def test_foreign_session_forbidden_even_for_multi_role_driver(db_session):
    charging, _ = await sample(db_session)
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=uuid4(), roles=frozenset({"driver", "admin"})
    )
    assert (
        await get(f"/api/v1/driver/charging/sessions/{charging.id}/invoice")
    ).status_code == 403
    assert (await get("/api/v1/driver/invoices")).json()["items"] == []


async def test_missing_session_and_in_progress(db_session):
    charging, _ = await sample(db_session, invoice=False)
    assert (
        await get("/api/v1/driver/charging/sessions/2147483647/invoice")
    ).status_code == 404
    charging.ended_at = None
    await db_session.flush()
    data = (await get(f"/api/v1/driver/charging/sessions/{charging.id}/invoice")).json()
    assert data["status"] == "in_progress" and data["total_vnd"] is None
    assert (await get("/api/v1/driver/invoices")).json()["items"] == []


@pytest.mark.parametrize(
    "path", ["/api/v1/driver/invoices", "/api/v1/driver/charging/sessions/1/invoice"]
)
async def test_anonymous_and_non_driver(path):
    assert (await get(path)).status_code == 401
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user_id=uuid4(), roles=frozenset({"operator"})
    )
    try:
        assert (await get(path)).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


async def test_invoice_read_ignores_later_tariff_changes(db_session):
    from src.modules.pricing.models import Tariff

    charging, _ = await sample(db_session)
    path = f"/api/v1/driver/charging/sessions/{charging.id}/invoice"
    before = (await get(path)).json()
    tariff = await db_session.get(Tariff, before["lines"][0]["tariff_id"])
    tariff.idle_rate_vnd_per_minute = 9999
    await db_session.flush()
    assert (await get(path)).json() == before


async def test_list_pagination_scopes_every_page(db_session):
    charging, driver = await sample(db_session)
    newer, _ = await sample(db_session, existing_driver=driver)
    first = (await get("/api/v1/driver/invoices?limit=1")).json()
    assert first["items"][0]["session_id"] == newer.id
    assert first["next_cursor"] == newer.id
    second = (await get(f"/api/v1/driver/invoices?limit=1&cursor={newer.id}")).json()
    assert second["items"][0]["session_id"] == charging.id
    assert second["next_cursor"] is None
