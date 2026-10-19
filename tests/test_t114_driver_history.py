from datetime import UTC, datetime, timedelta
from decimal import Decimal
from secrets import token_urlsafe

import httpx
import pytest
from sqlalchemy import select

from src.entrypoints.http import app
from src.modules.charging.models import ChargingSession, MeterSample
from src.modules.identity.models import Session, UserRole
from src.modules.identity.security import hash_session_token
from src.modules.stations.models import Connector
from tests.test_charging_sessions import setup
from tests.test_ocpp_control import db_session as isolated_database

# Each test commits real cookies/data into savepoints on a disposable PostgreSQL DB.
db_session = isolated_database
URL = "/api/v1/charging/my-sessions"


async def seed(db):
    station, charger, _, driver, *_ = await setup(db)
    _, other_charger, _, other_driver, *_ = await setup(db)
    stamp = datetime.now(UTC) - timedelta(hours=2)
    rows = {}
    for index, (name, owner, cp, closed, review, abnormal) in enumerate(
        [
            ("closed", driver, charger, True, False, False),
            ("review", driver, charger, True, True, False),
            ("abnormal", driver, charger, False, True, True),
            ("open", driver, charger, False, False, False),
            ("other_closed", other_driver, other_charger, True, True, False),
            ("other_open", other_driver, other_charger, False, True, True),
        ],
        2,
    ):
        connector = Connector(charge_point_id=cp.id, connector_number=index)
        db.add(connector)
        await db.flush()
        row = ChargingSession(
            charge_point_id=cp.id,
            connector_id=connector.id,
            driver_id=owner.id,
            tag_tail="TEST",
            authorization_status="Accepted",
            started_at=stamp,
            ended_at=stamp + timedelta(hours=1) if closed else None,
            meter_start_wh=1000,
            meter_stop_wh=2500 if closed else None,
            energy_kwh="1.5" if closed else None,
            review_reasons=["offline_timeout"] if review else [],
            abnormal_since=stamp if abnormal else None,
        )
        db.add(row)
        await db.flush()
        db.add(
            MeterSample(
                session_id=row.id,
                timestamp=stamp + timedelta(minutes=30),
                measurand="Energy.Active.Import.Register",
                phase="",
                location="Outlet",
                unit="Wh",
                value=2000,
            )
        )
        rows[name] = row.id
    tokens = []
    for owner in (driver, other_driver):
        token = token_urlsafe(32)
        db.add(
            Session(
                user_id=owner.id,
                token_hash=hash_session_token(token),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        tokens.append(token)
    await db.commit()
    return rows, tokens, station, driver


@pytest.mark.parametrize(
    "state,names",
    [
        ("all", ["closed", "review", "abnormal", "open"]),
        ("open", ["abnormal", "open"]),
        ("closed", ["closed", "review"]),
        ("review", ["review", "abnormal"]),
        ("abnormal", ["abnormal"]),
    ],
)
async def test_real_driver_cookies_filter_items_and_total(db_session, state, names):
    rows, tokens, station, _ = await seed(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        client.cookies.set("session", tokens[0])
        response = await client.get(URL, params={"state": state, "page_size": 1})
        assert response.status_code == 200
        data = response.json()
        expected = sorted((rows[name] for name in names), reverse=True)
        assert data["total"] == len(expected) and data["total_pages"] == len(expected)
        assert [item["id"] for item in data["items"]] == expected[:1]
        assert data["items"][0]["station_id"] == str(station.id)
        assert Decimal(data["items"][0]["latest_meter_wh"]) == Decimal(2000)
        for page in range(2, len(expected) + 1):
            part = (
                await client.get(
                    URL, params={"state": state, "page_size": 1, "page": page}
                )
            ).json()
            assert [item["id"] for item in part["items"]] == expected[page - 1 : page]
            assert part["total"] == len(expected)
        empty = (await client.get(URL, params={"state": state, "page": 99})).json()
        assert empty["items"] == [] and empty["total"] == len(expected)
        client.cookies.set("session", tokens[1])
        other = (await client.get(URL)).json()
        assert other["total"] == 2
        assert {item["id"] for item in other["items"]} == {
            rows["other_closed"],
            rows["other_open"],
        }


async def test_empty_driver_history_and_revoke_role_with_same_cookie(db_session):
    _, _, _, driver, *_ = await setup(db_session)
    token = token_urlsafe(32)
    db_session.add(
        Session(
            user_id=driver.id,
            token_hash=hash_session_token(token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get(URL)).status_code == 401
        client.cookies.set("session", token)
        assert (await client.get(URL)).json() == {
            "items": [],
            "total": 0,
            "page": 1,
            "total_pages": 0,
        }
        assignments = (
            await db_session.scalars(
                select(UserRole).where(UserRole.user_id == driver.id)
            )
        ).all()
        for assignment in assignments:
            await db_session.delete(assignment)
        await db_session.commit()
        assert (await client.get(URL)).status_code == 403


@pytest.mark.parametrize(
    "roles", [["admin"], ["station_owner"], ["accountant"], ["operator"]]
)
async def test_non_driver_roles_cannot_read_history(db_session, roles):
    from uuid import uuid4

    from src.modules.identity.authorization import CurrentActor
    from src.modules.identity.dependencies import get_current_actor

    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        uuid4(), frozenset(roles)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get(URL)).status_code == 403


@pytest.mark.parametrize(
    "query", ["state=invalid", "page=0", "page_size=0", "page_size=101"]
)
async def test_invalid_history_queries(db_session, query):
    _, tokens, _, _ = await seed(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        client.cookies.set("session", tokens[0])
        assert (await client.get(URL + "?" + query)).status_code == 422
