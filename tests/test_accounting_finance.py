from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from src.entrypoints.http import app
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.stations.models import ChargePoint
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.service import tru_vi
from tests.test_ocpp_control import db_session as isolated_session
from tests.test_t82_driver_invoice import sample

db_session = isolated_session
BASE = "/api/v1/accounting/finance"


def actor(role="accountant"):
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), frozenset({role})
    )


async def get(path, **params):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(BASE + path, params=params)


async def evidence(db):
    return (
        await db.scalar(select(func.count()).select_from(Invoice)),
        await db.scalar(select(func.count()).select_from(InvoiceLine)),
        await db.scalar(select(func.count()).select_from(WalletLedger)),
        list(
            (
                await db.execute(
                    select(Wallet.id, Wallet.balance_vnd).order_by(Wallet.id)
                )
            ).all()
        ),
    )


@pytest.mark.parametrize("role", ["admin", "driver", "operator", "station_owner"])
@pytest.mark.parametrize(
    "path", ["/sessions", "/invoices", "/stations", "/sessions/1", "/insights/sessions"]
)
async def test_financial_routes_deny_other_roles(db_session, role, path):
    actor(role)
    assert (await get(path)).status_code == 403


async def test_financial_routes_require_login(db_session):
    assert (await get("/sessions")).status_code == 401


async def test_insights_full_cohort_fees_money_precision_and_readonly(db_session):
    first, _ = await sample(db_session, total=9007199254740993)
    first.started_at = datetime(2026, 10, 9, 17, 30, tzinfo=UTC)
    second, _ = await sample(db_session, total=2500)
    second.started_at = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)
    await sample(db_session, invoice=False)
    await db_session.flush()
    before = await evidence(db_session)
    actor()
    response = await get("/insights/invoices", page_size=1)
    assert response.status_code == 200, response.text
    data = response.json()
    assert sum(row["sessions"] for row in data["timeline"]) == 2
    assert sum(int(row["invoice_vnd"]) for row in data["timeline"]) == 9007199254743493
    assert sum(row["sessions"] for row in data["stations"]) == 2
    assert {row["type"] for row in data["fees"]} == {"energy", "idle"}
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
    filtered = (await get("/insights/invoices", date_from=today, date_to=today)).json()
    assert filtered["timeline"][0]["period"] == today
    assert filtered["timeline"][0]["invoice_vnd"] == "9007199254743493"
    sessions_data = (
        await get(
            "/insights/sessions",
            date_from="2026-10-10",
            date_to="2026-10-10",
            q=str(first.id),
        )
    ).json()
    assert sessions_data["timeline"][0]["period"] == "2026-10-10"
    assert sessions_data["timeline"][0]["invoice_vnd"] == "9007199254740993"
    assert await evidence(db_session) == before


async def test_reconciliation_insights_age_and_priority_filter(db_session):
    old, _ = await sample(db_session, invoice=False)
    old.started_at = datetime.now(UTC) - timedelta(days=10)
    old.ended_at = datetime.now(UTC) - timedelta(days=9)
    recent, _ = await sample(db_session, invoice=False, review=True)
    recent.started_at = datetime.now(UTC) - timedelta(hours=2)
    recent.ended_at = datetime.now(UTC) - timedelta(hours=1, minutes=10)
    ongoing, _ = await sample(db_session, invoice=False)
    ongoing.ended_at = None
    await db_session.flush()
    actor()
    data = (await get("/insights/reconciliation")).json()
    assert sum(row["count"] for row in data["statuses"]) == 2
    assert {row["bucket"] for row in data["aging"]} == {"over_week", "under_day"}
    result = (await get("/sessions", attention=True)).json()
    assert result["items"][0]["session_id"] == recent.id
    result = (await get("/sessions", attention=True, age="over_week")).json()
    assert [row["session_id"] for row in result["items"]] == [old.id]
    data = (await get("/insights/reconciliation", age="under_day")).json()
    assert sum(row["count"] for row in data["aging"]) == 1


async def test_financial_summary_covers_all_pages_and_get_never_settles(db_session):
    first, _ = await sample(db_session, total=9007199254740993)
    await sample(db_session, total=2500)
    await sample(db_session, invoice=False)
    before = await evidence(db_session)
    actor()
    response = await get("/sessions", page_size=1)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 3 and data["total_pages"] == 3
    assert len(data["items"]) == 1
    assert data["summary"]["invoices"] == 2
    assert data["summary"]["invoice_total_vnd"] == "9007199254743493"
    assert data["summary"]["debited_total_vnd"] == "0"
    invoice = (await get(f"/sessions/{first.id}")).json()
    assert invoice["invoice_total_vnd"] == "9007199254740993"
    assert invoice["connector_number"] == 1
    assert {line["line_type"] for line in invoice["lines"]} == {"energy", "idle"}
    assert invoice["status"] == "pending_settlement"
    assert (await get("/invoices")).json()["total"] == 2
    assert await evidence(db_session) == before


async def test_paid_zero_and_legacy_are_not_confused_with_collected_money(db_session):
    paid, _ = await sample(db_session, total=3500)
    invoice = await db_session.scalar(
        select(Invoice).where(Invoice.session_id == paid.id)
    )
    await tru_vi(db_session, invoice=invoice)
    paid.settlement_completed_at = datetime.now(UTC)
    paid.settlement_reason = "debited"
    legacy, _ = await sample(db_session, total=5000)
    legacy.settlement_completed_at = datetime.now(UTC)
    legacy.settlement_reason = "legacy_exempt"
    zero, driver = await sample(db_session, invoice=False)
    db_session.add(
        Invoice(
            session_id=zero.id,
            driver_id=driver.id,
            station_id=(
                await db_session.scalar(
                    select(ChargePoint.station_id).where(
                        ChargePoint.id == zero.charge_point_id
                    )
                )
            ),
            total_vnd=0,
            rounding_rule="Zero",
        )
    )
    zero.settlement_completed_at = datetime.now(UTC)
    zero.settlement_reason = "zero_invoice"
    await db_session.flush()
    actor()
    data = (await get("/sessions")).json()
    assert data["summary"]["invoice_total_vnd"] == "8500"
    assert data["summary"]["debited_total_vnd"] == "3500"
    statuses = {r["session_id"]: r["status"] for r in data["items"]}
    assert statuses == {
        paid.id: "settled",
        zero.id: "settled",
        legacy.id: "legacy_exempt",
    }
    detail = (await get(f"/sessions/{paid.id}")).json()
    assert detail["ledger_amount_vnd"] == "-3500"
    assert detail["ledger_id"] is not None


async def test_unplug_review_and_attention_filters(db_session):
    waiting, _ = await sample(db_session, invoice=False)
    waiting.billing_lifecycle_version = 1
    pending, _ = await sample(db_session, invoice=False)
    review, _ = await sample(db_session, review=True, invoice=False)
    ongoing, _ = await sample(db_session, invoice=False)
    ongoing.ended_at = None
    await db_session.flush()
    actor()
    rows = (await get("/sessions", attention="true")).json()["items"]
    assert {r["session_id"] for r in rows} == {waiting.id, pending.id, review.id}
    assert (await get("/sessions", status="awaiting_unplug")).json()["items"][0][
        "session_id"
    ] == waiting.id
    assert (await get("/sessions", status="in_progress")).json()["items"][0][
        "session_id"
    ] == ongoing.id


async def test_search_station_and_vietnam_date_filters_apply_before_pagination(
    db_session,
):
    charging, driver = await sample(db_session)
    charging.started_at = datetime(2026, 10, 9, 17, 30, tzinfo=UTC)
    charging.ended_at = charging.started_at + timedelta(hours=1)
    await sample(db_session)
    await db_session.flush()
    actor()
    data = (
        await get(
            "/sessions",
            q=driver.email,
            date_from="2026-10-10",
            date_to="2026-10-10",
            page_size=1,
        )
    ).json()
    assert data["total"] == 1
    assert data["items"][0]["session_id"] == charging.id
    station = data["items"][0]["station_id"]
    assert (await get("/sessions", station_id=station)).json()["total"] == 1
    assert (await get("/sessions", q="%_")).json()["total"] == 0
    assert len((await get("/stations")).json()["items"]) == 2


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-10-11", "date_to": "2026-10-10"},
        {"page": 0},
        {"status": "paid"},
    ],
)
async def test_invalid_filters_are_rejected(db_session, params):
    actor()
    assert (await get("/sessions", **params)).status_code == 422


async def test_missing_details_and_no_mutation_endpoint(db_session):
    actor()
    assert (await get("/sessions/999999999")).status_code == 404
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post(BASE + "/sessions/1")).status_code == 405


async def test_settlement_marker_without_matching_ledger_is_not_reported_paid(
    db_session,
):
    charging, _ = await sample(db_session, total=3500)
    charging.settlement_completed_at = datetime.now(UTC)
    charging.settlement_reason = "debited"
    await db_session.flush()
    actor()
    before = await evidence(db_session)
    detail = (await get(f"/sessions/{charging.id}")).json()
    assert detail["status"] == "needs_review"
    assert "settlement_ledger_mismatch" in detail["review_reasons"]
    assert detail["debited_vnd"] == "0"
    assert (await get("/sessions", status="settled")).json()["total"] == 0
    assert await evidence(db_session) == before


async def test_invoice_for_wrong_driver_is_flagged_without_changing_evidence(
    db_session,
):
    charging, _ = await sample(db_session, invoice=False)
    _, other_driver = await sample(db_session, invoice=False)
    station_id = await db_session.scalar(
        select(ChargePoint.station_id).where(ChargePoint.id == charging.charge_point_id)
    )
    db_session.add(
        Invoice(
            session_id=charging.id,
            driver_id=other_driver.id,
            station_id=station_id,
            total_vnd=3500,
            rounding_rule="Evidence",
        )
    )
    await db_session.flush()
    actor()
    before = await evidence(db_session)
    detail = (await get(f"/sessions/{charging.id}")).json()
    assert detail["status"] == "needs_review"
    assert detail["invoice_total_vnd"] == "3500"
    assert detail["debited_vnd"] == "0"
    assert await evidence(db_session) == before
