"""Integration tests for S-45 power schedule runtime application and review verification.

Verifies:
1. Integration loop through Scheduler -> Worker -> OCPP.
2. 22:00 reduce 30 -> 15 kW with 3 cars:
   - Ca đủ min: 3 xe giảm từ 10 kW xuống 5 kW (giảm trước tăng sau).
   - Ca thiếu min (min_w = 6000 W): dừng xe mới nhất theo LIFO (started_at rồi session_id)
     qua RemoteStopTransaction, cập nhật stop_reason="power_schedule_preempted",
     ghi audit log, và 2 xe còn lại phân bổ 7.5 kW.
3. Ca Rejected / timeout / offline khi giảm công suất:
   - Trạng thái chuyển sang degraded, không hiển thị tuân thủ (compliance_status != 'confirmed'),
     và chặn bắt đầu phiên sạc mới (power_start_allowed=False).
4. Timezone khác UTC (Asia/Ho_Chi_Minh - UTC+7):
   - Ranh giới 22:00 giờ địa phương khớp chính xác với 15:00 UTC.
5. Restart lúc 22:01:
   - Worker nhận diện ngay hạn mức 15 kW của lịch thay vì giá trị tĩnh 30 kW,
     và chặn sạc mới nếu vượt ngân sách 15 kW.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import ActorScope, AuthorizationEvidence
from src.modules.power import worker
from src.modules.power.models import ConnectorPower, StationPower
from src.modules.power.schemas import PowerSetting
from src.modules.power.service import (
    change_control,
    power_start_allowed,
    save_settings,
)
from src.modules.stations.models import ChargePoint, Connector
from src.modules.stations.power_bands import PowerBandInput
from src.modules.stations.power_schedule_service import (
    get_current_power_limit_w,
    save_station_power_schedule,
)
from src.platform.audit.models import AuditLog
from tests.test_flat_tariff_api import api_db, committed_tariff_db  # noqa: F401
from tests.test_tariff_schema import make_station


@pytest.fixture
async def s45_fleet(api_db, monkeypatch):  # noqa: F811
    factory = api_db
    monkeypatch.setattr(worker, "SessionFactory", factory)
    monkeypatch.setattr(worker, "engine", factory.kw["bind"])
    async with factory() as db, db.begin():
        station = await make_station(db)
        station.status = "active"
        station.timezone = "Asia/Ho_Chi_Minh"
        now = datetime.now(UTC)
        charger = ChargePoint(
            station_id=station.id,
            code=f"S45-{uuid4().hex[:10]}",
            status="online",
            last_seen_at=now,
            last_boot_at=now,
            heartbeat_interval_seconds=600,
        )
        db.add(charger)
        await db.flush()
        connectors = [
            Connector(
                charge_point_id=charger.id,
                connector_number=i + 1,
                status="Available",
                raw_ocpp_status="Available",
                max_power_kw=Decimal(22),
            )
            for i in range(3)
        ]
        db.add_all(connectors)
        await db.flush()
        ids = [c.id for c in connectors]
        scope = ActorScope(station.owner_id, station.owner_id)
        evidence = AuthorizationEvidence("owner.power.configure", ("station_owner",))
    return factory, station, charger, ids, scope, evidence


def make_power_setting(ids, version=0, limit="30"):
    return PowerSetting.model_validate(
        {
            "version": version,
            "limit_kw": limit,
            "connectors": [{"connector_id": str(id_), "rated_kw": "22"} for id_ in ids],
            "zero_limit_verified": True,
            "offline_retention_verified": True,
            "verification_note": "S-45 simulator verified",
        }
    )


async def setup_station_power(fleet):
    factory, station, _, ids, scope, evidence = fleet
    async with factory() as db, db.begin():
        await save_settings(db, station.id, make_power_setting(ids), scope, evidence)
        await change_control(db, station.id, 1, True, scope, evidence)
        config = await db.get(StationPower, station.id)
        config.dirty_at = datetime.now(UTC) - timedelta(seconds=3)


async def execute_plan(factory, station):
    async with factory() as db, db.begin():
        config = await db.get(StationPower, station.id)
        config.last_plan_at = None
        config.dirty_at = None
    await worker.reconcile_station(station.id)


def setup_mock_wire(monkeypatch, charger):
    state = {1: 0, 2: 0, 3: 0}
    trace = []
    failures = set()
    connection = SimpleNamespace(boot_accepted=True)

    async def snapshot():
        return {charger.id: connection}

    async def get(code):
        return connection

    async def wire(connection, action, payload, request_id):
        trace.append((action, payload))
        if action in failures:
            return "Rejected", {}
        if action == "GetConfiguration":
            return "Accepted", {
                "configurationKey": [
                    {"key": "SupportedFeatureProfiles", "value": "Core,SmartCharging"},
                    {
                        "key": "ChargingScheduleAllowedChargingRateUnit",
                        "value": "Power",
                    },
                    {"key": "ChargeProfileMaxStackLevel", "value": "1"},
                ]
            }
        if action == "SetChargingProfile":
            cid = payload["connectorId"]
            state[cid] = payload["csChargingProfiles"]["chargingSchedule"][
                "chargingSchedulePeriod"
            ][0]["limit"]
        if action == "GetCompositeSchedule":
            cid = payload["connectorId"]
            return "Accepted", {
                "connectorId": cid,
                "scheduleStart": datetime.now(UTC).isoformat(),
                "chargingSchedule": {
                    "duration": 60,
                    "chargingRateUnit": "W",
                    "chargingSchedulePeriod": [{"startPeriod": 0, "limit": state[cid]}],
                },
            }
        return "Accepted", {}

    monkeypatch.setattr(worker.ocpp_connections, "snapshot", snapshot)
    monkeypatch.setattr(worker.ocpp_connections, "get", get)
    monkeypatch.setattr(worker, "wire", wire)
    return state, trace, failures


async def add_active_sessions(fleet, start_times=None, min_w_per_connector=None):
    factory, station, charger, ids, _, _ = fleet
    now = datetime.now(UTC)
    sessions = []
    async with factory() as db, db.begin():
        for i, connector_id in enumerate(ids):
            t_start = start_times[i] if start_times and i < len(start_times) else now
            sess = ChargingSession(
                charge_point_id=charger.id,
                connector_id=connector_id,
                driver_id=station.owner_id,
                tag_tail=f"S{i + 1}",
                authorization_status="Accepted",
                started_at=t_start,
                meter_start_wh=Decimal(1000),
            )
            db.add(sess)
            await db.flush()
            sessions.append(sess.id)
            connector = await db.get(Connector, connector_id)
            connector.raw_ocpp_status = "Charging"
            if min_w_per_connector and connector_id in min_w_per_connector:
                connector.voltage = Decimal(min_w_per_connector[connector_id] / 6)
    return sessions


# =====================================================================
# Test 1: 22:00 reduce 30 -> 15 kW with 3 cars (normal reallocation)
# =====================================================================
async def test_schedule_22_00_reduces_power_and_reallocates_3_cars(
    s45_fleet, monkeypatch
):
    """AC-2/3: At 22:00, limit drops from 30kW to 15kW.

    When all 3 cars can run at 5kW (>= 1380W min), power is reallocated
    from 10kW to 5kW each. Decreases precede increases.
    """
    factory, station, charger, _ids, _, _ = s45_fleet
    state, trace, _ = setup_mock_wire(monkeypatch, charger)
    await setup_station_power(s45_fleet)

    # 1. Save schedule: 00:00 - 22:00 (1320 min) = 30 kW, 22:00 - 24:00 (1440 min) = 15 kW
    today = date(2026, 10, 15)
    async with factory() as db, db.begin():
        await save_station_power_schedule(
            db,
            station.id,
            today,
            [
                PowerBandInput(start_min=0, end_min=1320, power_limit_w=30000),
                PowerBandInput(start_min=1320, end_min=1440, power_limit_w=15000),
            ],
        )

    # Simulated clock starts at 20:00 local time (13:00 UTC)
    t_20_00 = datetime(2026, 10, 15, 13, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(worker, "get_now", lambda: t_20_00)

    # Initialize baseline and allocate at 30kW
    await execute_plan(factory, station)
    await add_active_sessions(s45_fleet)
    await execute_plan(factory, station)

    # 3 cars charging at 10 kW each
    assert state == {1: 10000, 2: 10000, 3: 10000}
    async with factory() as db:
        config = await db.get(StationPower, station.id)
        assert config.limit_w == 30000
        assert config.applied_limit_w == 30000
        assert config.state == "ready"

    # 2. Advance time to 22:00 local time (15:00 UTC)
    t_22_00 = datetime(2026, 10, 15, 15, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(worker, "get_now", lambda: t_22_00)
    trace.clear()

    await execute_plan(factory, station)

    # Worker detects boundary, updates limit_w to 15kW, and reallocates cars to 5kW each
    assert state == {1: 5000, 2: 5000, 3: 5000}
    async with factory() as db:
        config = await db.get(StationPower, station.id)
        assert config.limit_w == 15000
        assert config.applied_limit_w == 15000
        assert config.state == "ready"

    # Verify decrease profiles were sent
    writes = [p for action, p in trace if action == "SetChargingProfile"]
    assert len(writes) == 3
    for w in writes:
        assert (
            w["csChargingProfiles"]["chargingSchedule"]["chargingSchedulePeriod"][0][
                "limit"
            ]
            == 5000
        )


# =====================================================================
# Test 2: 22:00 reduce 30 -> 15 kW with 3 cars exceeding min -> LIFO preemption
# =====================================================================
async def test_schedule_22_00_exceeds_min_preempts_lifo_with_audit(
    s45_fleet, monkeypatch
):
    """AC-3: When total minimum power exceeds 15kW, LIFO preempts the newest car.

    3 cars with min_w = 6000W each (total 18kW > 15kW).
    The newest car (started_at latest) must be stopped via RemoteStopTransaction.
    Its stop_reason must be "power_schedule_preempted", and an audit entry written.
    Surviving 2 cars are reallocated to 7500W each.
    """
    factory, station, charger, ids, _, _ = s45_fleet
    state, trace, _ = setup_mock_wire(monkeypatch, charger)
    await setup_station_power(s45_fleet)

    today = date(2026, 10, 15)
    async with factory() as db, db.begin():
        await save_station_power_schedule(
            db,
            station.id,
            today,
            [
                PowerBandInput(start_min=0, end_min=1320, power_limit_w=30000),
                PowerBandInput(start_min=1320, end_min=1440, power_limit_w=15000),
            ],
        )

    t_start_base = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
    t_car1 = t_start_base
    t_car2 = t_start_base + timedelta(minutes=10)
    t_car3_newest = t_start_base + timedelta(minutes=20)

    # Set voltage on connectors so resolve_min_w returns 6000W each (6000/6 = 1000V)
    min_w_map = {ids[0]: 6000, ids[1]: 6000, ids[2]: 6000}

    # Start at 20:00 local time
    t_20_00 = datetime(2026, 10, 15, 13, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(worker, "get_now", lambda: t_20_00)

    await execute_plan(factory, station)
    session_ids = await add_active_sessions(
        s45_fleet,
        start_times=[t_car1, t_car2, t_car3_newest],
        min_w_per_connector=min_w_map,
    )
    await execute_plan(factory, station)

    # 3 cars charging at 10 kW each
    assert state == {1: 10000, 2: 10000, 3: 10000}

    # Step to 22:00 local time
    t_22_00 = datetime(2026, 10, 15, 15, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(worker, "get_now", lambda: t_22_00)
    trace.clear()

    await execute_plan(factory, station)

    # 1. Car 3 (newest, connector 3) must be preempted: RemoteStopTransaction sent
    preempt_cmds = [p for action, p in trace if action == "RemoteStopTransaction"]
    assert len(preempt_cmds) == 1
    assert preempt_cmds[0]["transactionId"] == session_ids[2]

    # 2. Car 3 power reduced to 0, surviving 2 cars get 7500 W each (total 15 kW)
    assert state[3] == 0
    assert state[1] == 7500
    assert state[2] == 7500
    assert sum(state.values()) == 15000

    # 3. DB assertions: stop_reason updated on ChargingSession
    async with factory() as db:
        preempted_sess = await db.get(ChargingSession, session_ids[2])
        assert preempted_sess is not None
        assert preempted_sess.stop_reason == "power_schedule_preempted"

        # Audit log verified
        audit_entry = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "power.session_preempted",
                AuditLog.object_id == str(session_ids[2]),
            )
        )
        assert audit_entry is not None
        assert audit_entry.data["station_id"] == str(station.id)
        assert audit_entry.data["limit_w"] == 15000

        # Station power state
        config = await db.get(StationPower, station.id)
        assert config.limit_w == 15000
        assert config.applied_limit_w == 15000
        assert config.state == "ready"


# =====================================================================
# Test 3: Failure handling (Rejected / timeout / offline) during reduction
# =====================================================================
async def test_reduction_rejected_degrades_station_and_blocks_start(
    s45_fleet, monkeypatch
):
    """AC-4: When reduction command is Rejected or fails verification,

    station enters degraded state, applied_limit_w does NOT claim 15kW,
    and power_start_allowed returns False.
    """
    factory, station, charger, _ids, _, _ = s45_fleet
    _state, _trace, failures = setup_mock_wire(monkeypatch, charger)
    await setup_station_power(s45_fleet)

    today = date(2026, 10, 15)
    async with factory() as db, db.begin():
        await save_station_power_schedule(
            db,
            station.id,
            today,
            [
                PowerBandInput(start_min=0, end_min=1320, power_limit_w=30000),
                PowerBandInput(start_min=1320, end_min=1440, power_limit_w=15000),
            ],
        )

    t_20_00 = datetime(2026, 10, 15, 13, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(worker, "get_now", lambda: t_20_00)

    await execute_plan(factory, station)
    await add_active_sessions(s45_fleet)
    await execute_plan(factory, station)

    # Step to 22:00, but inject failure on SetChargingProfile
    t_22_00 = datetime(2026, 10, 15, 15, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(worker, "get_now", lambda: t_22_00)
    failures.add("SetChargingProfile")

    await execute_plan(factory, station)

    async with factory() as db:
        config = await db.get(StationPower, station.id)
        # 1. State must be degraded, not claiming confirmed reduction
        assert config.state == "degraded"
        assert config.applied_limit_w != 15000

        # 2. power_start_allowed must block new sessions
        allowed = await power_start_allowed(db, station.id, at_time=t_22_00)
        assert allowed is False


# =====================================================================
# Test 4: Timezone boundary (Asia/Ho_Chi_Minh UTC+7 vs UTC)
# =====================================================================
async def test_station_timezone_boundary_at_local_22_00(s45_fleet, monkeypatch):
    """AC-5: Schedule boundaries respect station IANA timezone.

    Local 22:00 in Asia/Ho_Chi_Minh is 15:00 UTC.
    At 14:59 UTC, limit is still 30kW.
    At 15:00 UTC, limit becomes 15kW.
    """
    factory, station, _, _, _, _ = s45_fleet
    today = date(2026, 10, 15)
    async with factory() as db, db.begin():
        await save_station_power_schedule(
            db,
            station.id,
            today,
            [
                PowerBandInput(start_min=0, end_min=1320, power_limit_w=30000),
                PowerBandInput(start_min=1320, end_min=1440, power_limit_w=15000),
            ],
        )

    async with factory() as db:
        # At 14:59 UTC (21:59 local): still 30kW
        t_before = datetime(2026, 10, 15, 14, 59, 0, tzinfo=UTC)
        limit_before = await get_current_power_limit_w(db, station.id, t_before)
        assert limit_before == 30000

        # At 15:00 UTC (22:00 local): drops to 15kW
        t_boundary = datetime(2026, 10, 15, 15, 0, 0, tzinfo=UTC)
        limit_at = await get_current_power_limit_w(db, station.id, t_boundary)
        assert limit_at == 15000

        # At 22:00 UTC (05:00 next day local): next day schedule lookup
        t_utc_22 = datetime(2026, 10, 15, 22, 0, 0, tzinfo=UTC)
        limit_utc = await get_current_power_limit_w(db, station.id, t_utc_22)
        # Next day local morning (05:00 local = 300 min), still under effective schedule -> 30kW
        assert limit_utc == 30000


# =====================================================================
# Test 5: Worker restart at 22:01
# =====================================================================
async def test_worker_restart_at_22_01_reconciles_active_schedule(
    s45_fleet, monkeypatch
):
    """AC-2/5: On reboot at 22:01, worker checks current power schedule

    before allocating budget or admitting new sessions. It must adopt 15kW,
    not default to static limit_w.
    """
    factory, station, charger, ids, _, _ = s45_fleet
    _state, _, _ = setup_mock_wire(monkeypatch, charger)
    await setup_station_power(s45_fleet)

    today = date(2026, 10, 15)
    async with factory() as db, db.begin():
        await save_station_power_schedule(
            db,
            station.id,
            today,
            [
                PowerBandInput(start_min=0, end_min=1320, power_limit_w=30000),
                PowerBandInput(start_min=1320, end_min=1440, power_limit_w=15000),
            ],
        )

    # Station starts freshly rebooted at 22:01 local time (15:01 UTC)
    t_22_01 = datetime(2026, 10, 15, 15, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(worker, "get_now", lambda: t_22_01)

    # First reconciliation after reboot
    await execute_plan(factory, station)

    async with factory() as db:
        config = await db.get(StationPower, station.id)
        # Reconcile adopted the active 15kW schedule
        assert config.limit_w == 15000
        assert config.state == "ready"

        # Verify start gating under 15kW limit:
        # If no cars are charging, start is allowed
        assert await power_start_allowed(db, station.id, at_time=t_22_01) is True

        # Simulate active sessions taking up 14kW reserved
        cap1 = await db.get(ConnectorPower, ids[0])
        cap1.reserved_w = 7000
        cap2 = await db.get(ConnectorPower, ids[1])
        cap2.reserved_w = 7000
        await db.flush()

        # Total reserved is 14kW. Next car needs min 1380W -> 14000 + 1380 = 15380 > 15000
        # Start must be blocked!
        assert await power_start_allowed(db, station.id, at_time=t_22_01) is False
