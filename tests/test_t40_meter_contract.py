from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from src.entrypoints.http import app
from src.modules.billing.segmentation import MeterValue, interpolate_meter_value
from src.modules.charging.meter_units import numeric_sample
from src.modules.charging.models import ChargingSession, MeterSample
from src.modules.charging.payloads import SamplePayload
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.platform.database.session import get_db_session
from tests.test_charging_sessions import call, meter_payload, setup, start


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        ("1", "kWh", "1000"),
        ("1000", "Wh", "1000"),
        ("1000", None, "1000"),
        ("0.1", "kWh", "100"),
        ("0.000001", "kWh", "0.001"),
        ("1234.567891", "Wh", "1234.567891"),
        ("0", "kWh", "0"),
    ],
)
def test_canonical_energy_is_decimal_wh(value, unit, expected):
    sample = SamplePayload(value=value, **({"unit": unit} if unit is not None else {}))
    result = numeric_sample(sample)
    assert result == (Decimal(expected), "Wh")
    assert isinstance(result[0], Decimal)
    # Reading canonical Wh must not apply the original kWh factor a second time.
    assert numeric_sample(SamplePayload(value=str(result[0]), unit=result[1])) == result


@pytest.mark.parametrize(
    "value,unit,format",
    [
        ("NaN", "Wh", "Raw"),
        ("Infinity", "Wh", "Raw"),
        ("-Infinity", "Wh", "Raw"),
        ("invalid", "Wh", "Raw"),
        ("1000000000000000000", "Wh", "Raw"),
        ("1", "J", "Raw"),
        ("1", "Wh", "SignedData"),
    ],
)
def test_unusable_energy_is_not_coerced_to_zero(value, unit, format):
    assert numeric_sample(SamplePayload(value=value, unit=unit, format=format)) is None


@pytest.mark.parametrize(
    "measurand,value,unit,expected,canonical",
    [
        ("Power.Active.Import", "1.5", "kW", "1500", "W"),
        ("Current.Import", "32.1", "A", "32.1", "A"),
        ("Voltage", "230", "V", "230", "V"),
    ],
)
def test_other_quantities_keep_their_own_units(
    measurand, value, unit, expected, canonical
):
    assert numeric_sample(
        SamplePayload(value=value, unit=unit, measurand=measurand)
    ) == (Decimal(expected), canonical)


@pytest.mark.asyncio
@pytest.mark.parametrize("value,unit", [(1, "kWh"), (1000, "Wh"), (1000, None)])
async def test_ocpp_storage_api_and_reader_share_wh_contract(db_session, value, unit):
    station, _, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC)
    tid = (await start(db_session, conn, tag, stamp, meter=0)).payload["transactionId"]
    at = stamp + timedelta(seconds=10)
    extra = {"unit": unit} if unit is not None else {}
    reply = await call(
        db_session, conn, "MeterValues", meter_payload(tid, at, value, **extra)
    )
    assert reply.kind == 3
    # Another unit for the same physical observation is still the same sample.
    await call(db_session, conn, "MeterValues", meter_payload(tid, at, 1000, unit="Wh"))
    rows = (
        await db_session.scalars(
            select(MeterSample).where(MeterSample.session_id == tid)
        )
    ).all()
    assert len(rows) == 1
    sample = rows[0]
    assert (sample.value, sample.unit) == (Decimal(1000), "Wh")
    meter, interpolated = interpolate_meter_value(at, [MeterValue(at, sample.value)])
    assert meter == Decimal(1000) and not interpolated

    async def database():
        yield db_session

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        station.owner_id, frozenset({"station_owner"})
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/v1/charging/sessions/{tid}/samples")
        assert response.status_code == 200
        payload = response.json()["items"][0]
        assert payload["unit"] == "Wh" and Decimal(payload["value"]) == Decimal(1000)
    finally:
        app.dependency_overrides.clear()

    await call(
        db_session,
        conn,
        "StopTransaction",
        {
            "transactionId": tid,
            "meterStop": 1000,
            "timestamp": (stamp + timedelta(seconds=20)).isoformat(),
        },
    )
    transaction = await db_session.get(ChargingSession, tid)
    assert transaction.energy_kwh == Decimal(1)
    assert transaction.review_reasons == []
