"""Durable, conservative power plans; no DB transaction waits on a charger."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import WebSocketDisconnect
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from src.config import settings
from src.modules.charging.models import ChargingSession
from src.modules.ocpp.connection_registry import OcppConnection, ocpp_connections
from src.modules.power.allocation import allocate_watts
from src.modules.power.models import ConnectorPower, PowerCommand, StationPower
from src.modules.stations.models import ChargePoint, Connector
from src.platform.database.session import SessionFactory, engine

logger = logging.getLogger("csms.power")


@dataclass(frozen=True)
class Device:
    connector_id: UUID
    charge_point_id: UUID
    code: str
    number: int
    boot_at: datetime | None
    rated_w: int
    profile_id: int
    reserved_w: int
    confirmed_w: int
    baseline_boot_at: datetime | None
    pending_command_id: UUID | None
    transaction_id: int | None
    needs_power: bool
    online: bool


async def devices(station_id: UUID) -> list[Device]:
    now = datetime.now(UTC)
    sockets = await ocpp_connections.snapshot()
    async with SessionFactory() as db:
        active = {
            row.connector_id: row.id
            for row in await db.scalars(
                select(ChargingSession)
                .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
                .where(
                    ChargePoint.station_id == station_id,
                    ChargingSession.ended_at.is_(None),
                )
            )
        }
        result = []
        rows = (
            await db.execute(
                select(ConnectorPower, Connector, ChargePoint)
                .join(Connector, Connector.id == ConnectorPower.connector_id)
                .join(ChargePoint, ChargePoint.id == Connector.charge_point_id)
                .where(ConnectorPower.station_id == station_id)
                .order_by(ConnectorPower.connector_id)
            )
        ).all()
        for cap, connector, charger in rows:
            connection = sockets.get(charger.id)
            live = bool(
                connection
                and connection.boot_accepted
                and charger.last_seen_at
                and charger.last_seen_at
                >= now - timedelta(seconds=2 * charger.heartbeat_interval_seconds)
                and connector.archived_at is None
                and charger.archived_at is None
            )
            result.append(
                Device(
                    cap.connector_id,
                    charger.id,
                    charger.code.strip().lower(),
                    connector.connector_number,
                    charger.last_boot_at,
                    cap.rated_w,
                    cap.profile_id,
                    cap.reserved_w,
                    cap.confirmed_w,
                    cap.baseline_boot_at,
                    cap.pending_command_id,
                    active.get(connector.id),
                    connector.raw_ocpp_status == "Charging" and connector.id in active,
                    live,
                )
            )
        return result


async def wire(
    connection: OcppConnection,
    action: str,
    payload: dict[str, object],
    request_id: UUID,
) -> tuple[str, dict[str, object]]:
    try:
        reply = await connection.call(
            action,
            payload,
            timeout=settings.power_command_timeout_seconds,
            message_id=str(request_id),
        )
        if reply.kind != 3:
            return "ProtocolError", {}
        if action == "GetConfiguration":
            return "Accepted", reply.payload
        status = reply.payload.get("status")
        if status not in {"Accepted", "Rejected", "Unknown"}:
            return "ProtocolError", {}
        return str(status), reply.payload
    except TimeoutError:
        return "Timeout", {}
    except (ConnectionError, OSError, RuntimeError, WebSocketDisconnect):
        return "Disconnected", {}


async def command(
    device: Device,
    station_id: UUID,
    generation: int,
    action: str,
    payload: dict[str, object],
    request_id: UUID | None = None,
) -> tuple[str, dict[str, object]]:
    intent_id = request_id or uuid4()
    async with SessionFactory() as db, db.begin():
        existing = await db.get(PowerCommand, intent_id)
        if existing is None:
            db.add(
                PowerCommand(
                    id=intent_id,
                    station_id=station_id,
                    connector_id=device.connector_id,
                    generation=generation,
                    action=action,
                    payload=payload,
                )
            )
        elif existing.action != action or existing.payload != payload:
            raise ValueError("Power intent payload mismatch")
    connection = await ocpp_connections.get(device.code)
    outcome, response = (
        await wire(connection, action, payload, intent_id)
        if connection and connection.boot_accepted
        else ("Offline", {})
    )
    async with SessionFactory() as db, db.begin():
        intent = await db.get(PowerCommand, intent_id)
        assert intent is not None
        intent.status = outcome
        intent.completed_at = datetime.now(UTC)
    return outcome, response


async def capabilities(device: Device, station_id: UUID, generation: int) -> bool:
    status, payload = await command(
        device,
        station_id,
        generation,
        "GetConfiguration",
        {
            "key": [
                "SupportedFeatureProfiles",
                "ChargingScheduleAllowedChargingRateUnit",
                "ChargeProfileMaxStackLevel",
            ]
        },
    )
    values = payload.get("configurationKey")
    if status != "Accepted" or not isinstance(values, list):
        return False
    config = {
        entry.get("key"): entry.get("value")
        for entry in values
        if isinstance(entry, dict)
    }
    try:
        return (
            "SmartCharging"
            in str(config.get("SupportedFeatureProfiles", "")).split(",")
            and bool(
                {"Power", "W"}
                & set(
                    str(
                        config.get("ChargingScheduleAllowedChargingRateUnit", "")
                    ).split(",")
                )
            )
            and int(str(config.get("ChargeProfileMaxStackLevel", "-1"))) >= 1
        )
    except ValueError:
        return False


def profile(device: Device, watts: int, baseline: bool = False) -> dict[str, object]:
    charging: dict[str, object] = {
        "chargingProfileId": device.profile_id * 2 + (0 if baseline else 1),
        "stackLevel": 0 if baseline else 1,
        "chargingProfilePurpose": "TxDefaultProfile"
        if baseline or device.transaction_id is None
        else "TxProfile",
        "chargingProfileKind": "Absolute",
        "chargingSchedule": {
            "chargingRateUnit": "W",
            "chargingSchedulePeriod": [{"startPeriod": 0, "limit": watts}],
        },
    }
    if not baseline and device.transaction_id is not None:
        charging["transactionId"] = device.transaction_id
    return {"connectorId": device.number, "csChargingProfiles": charging}


async def verify_limit(
    device: Device, station_id: UUID, generation: int, watts: int
) -> bool:
    outcome, payload = await command(
        device,
        station_id,
        generation,
        "GetCompositeSchedule",
        {"connectorId": device.number, "duration": 60, "chargingRateUnit": "W"},
    )
    schedule = payload.get("chargingSchedule")
    if (
        outcome != "Accepted"
        or payload.get("connectorId") != device.number
        or not isinstance(schedule, dict)
        or schedule.get("chargingRateUnit") != "W"
    ):
        return False
    periods = schedule.get("chargingSchedulePeriod")
    if not isinstance(periods, list) or not periods:
        return False
    # No future increase is permitted within the readback horizon.
    return (
        all(
            isinstance(p, dict)
            and type(p.get("limit")) in {int, float}
            and 0 <= p["limit"] <= watts
            for p in periods
        )
        and periods[0].get("startPeriod") == 0
    )


async def set_limit(
    device: Device,
    station_id: UUID,
    generation: int,
    watts: int,
    *,
    baseline: bool = False,
) -> bool:
    payload = profile(device, watts, baseline)
    async with SessionFactory() as db, db.begin():
        config = await db.scalar(
            select(StationPower)
            .where(StationPower.station_id == station_id)
            .with_for_update()
        )
        cap = await db.get(ConnectorPower, device.connector_id)
        assert config is not None and cap is not None
        if watts > cap.reserved_w:
            if config.generation != generation:
                return False
            # Serialize admission, not socket I/O: concurrent charger increases
            # must see the reservations already committed by their peers.
            total = await db.scalar(
                select(func.sum(ConnectorPower.reserved_w)).where(
                    ConnectorPower.station_id == station_id
                )
            )
            if int(total or 0) - cap.reserved_w + watts > config.limit_w:
                return False
        if cap.pending_command_id:
            prior = await db.get(PowerCommand, cap.pending_command_id)
            if prior and prior.payload == payload:
                request_id = prior.id
            else:
                request_id = uuid4()
        else:
            request_id = uuid4()
        if await db.get(PowerCommand, request_id) is None:
            db.add(
                PowerCommand(
                    id=request_id,
                    station_id=station_id,
                    connector_id=device.connector_id,
                    generation=generation,
                    action="SetChargingProfile",
                    payload=payload,
                )
            )
        # Reserve before send so a lost ACK/process crash cannot lend these watts twice.
        cap.reserved_w = max(cap.reserved_w, watts)
        cap.pending_command_id = request_id
        cap.desired_w = watts
    status, _ = await command(
        device, station_id, generation, "SetChargingProfile", payload, request_id
    )
    if status != "Accepted" or not await verify_limit(
        device, station_id, generation, watts
    ):
        return False
    async with SessionFactory() as db, db.begin():
        cap = await db.get(ConnectorPower, device.connector_id)
        assert cap is not None
        cap.confirmed_w = watts
        cap.reserved_w = watts
        cap.pending_command_id = None
        if baseline:
            cap.baseline_boot_at = device.boot_at
    return True


async def degrade(
    station_id: UUID, generation: int, issue: str, failed: Device | None = None
) -> None:
    async with SessionFactory() as db, db.begin():
        config = await db.scalar(
            select(StationPower)
            .where(StationPower.station_id == station_id)
            .with_for_update()
        )
        assert config is not None
        config.state = "degraded"
        config.issue = issue
    # Persist the stop intent too. An Accepted stop does not release reserved_w.
    if failed and failed.transaction_id is not None:
        await command(
            failed,
            station_id,
            generation,
            "RemoteStopTransaction",
            {"transactionId": failed.transaction_id},
        )
    logger.warning("power_degraded station=%s reason=%s", station_id, issue)


async def apply_phase(
    changes: list[Device],
    targets: dict[UUID, int],
    station_id: UUID,
    generation: int,
) -> bool:
    """Bound charger concurrency; finish all in-flight writes before returning."""
    groups: dict[UUID, list[Device]] = {}
    for device in changes:
        groups.setdefault(device.charge_point_id, []).append(device)
    slots = asyncio.Semaphore(5)

    async def apply_charger(group: list[Device]) -> Device | None:
        async with slots:
            # Keep one request/readback sequence at a time on each OCPP socket.
            for device in group:
                if not await set_limit(
                    device, station_id, generation, targets[device.connector_id]
                ):
                    return device
        return None

    results = await asyncio.gather(
        *(apply_charger(group) for group in groups.values()), return_exceptions=True
    )
    # Do not release the station lock while sibling writes are still running.
    for result in results:
        if isinstance(result, BaseException):
            raise result
    failed = [result for result in results if isinstance(result, Device)]
    for device in failed:
        await degrade(station_id, generation, "power_profile_not_verified", device)
    return not failed


async def reconcile_station(station_id: UUID) -> None:
    # Session-scoped advisory lock survives transaction commits, preventing competing workers.
    key = station_id.int % (2**63 - 1)
    async with engine.connect() as lock:
        acquired = await lock.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        )
        await lock.commit()
        if not acquired:
            return
        try:
            await _reconcile(station_id)
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            await lock.commit()


async def _reconcile(station_id: UUID) -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as db, db.begin():
        config = await db.scalar(
            select(StationPower)
            .where(StationPower.station_id == station_id)
            .with_for_update()
        )
        if config is None or not config.enabled:
            return
        if config.last_plan_at and now - config.last_plan_at < timedelta(seconds=5):
            return
        if config.dirty_at and now - config.dirty_at < timedelta(seconds=2):
            return
        generation, limit = config.generation, config.limit_w
        disabling = not config.target_enabled
        config.last_plan_at = now
    inputs = await devices(station_id)
    if not inputs:
        await degrade(station_id, generation, "power_configuration_incomplete")
        return
    # Registered connectors added after commissioning must not escape the baseline gate.
    async with SessionFactory() as db:
        count = len(
            list(
                await db.scalars(
                    select(Connector.id)
                    .join(ChargePoint)
                    .where(
                        ChargePoint.station_id == station_id,
                        Connector.archived_at.is_(None),
                        ChargePoint.archived_at.is_(None),
                    )
                )
            )
        )
    if count != len(inputs):
        await degrade(station_id, generation, "power_configuration_incomplete")
        return
    if disabling:
        for device in inputs:
            if device.transaction_id is not None or not device.online:
                await degrade(
                    station_id, generation, "power_disable_waiting_for_device"
                )
                return
            # First install zero limits; only then clear CSMS-owned profiles at idle connectors.
            if not await set_limit(device, station_id, generation, 0, baseline=True):
                await degrade(station_id, generation, "power_disable_failed", device)
                return
        for device in inputs:
            for baseline in (False, True):
                profile_id = device.profile_id * 2 + (0 if baseline else 1)
                outcome, _ = await command(
                    device,
                    station_id,
                    generation,
                    "ClearChargingProfile",
                    {"id": profile_id},
                )
                if outcome not in {"Accepted", "Unknown"}:
                    await degrade(
                        station_id, generation, "power_disable_failed", device
                    )
                    return
        async with SessionFactory() as db, db.begin():
            config = await db.get(StationPower, station_id)
            assert config is not None
            config.enabled = False
            config.state = "disabled"
            config.issue = None
        return
    for device in inputs:
        if device.baseline_boot_at != device.boot_at or device.baseline_boot_at is None:
            if not device.online or not await capabilities(
                device, station_id, generation
            ):
                await degrade(
                    station_id, generation, "power_capability_unverified", device
                )
                return
            if not await set_limit(device, station_id, generation, 0, baseline=True):
                await degrade(station_id, generation, "power_baseline_failed", device)
                return
    inputs = await devices(station_id)
    pinned = sum(device.reserved_w for device in inputs if not device.online)
    if pinned > limit:
        await degrade(station_id, generation, "offline_budget_exceeds_requested_limit")
        return
    demands = {
        device.connector_id: device.rated_w if device.needs_power else 0
        for device in inputs
        if device.online
    }
    targets = allocate_watts(limit - pinned, demands)
    changes = [
        device
        for device in inputs
        if device.online
        and (
            targets[device.connector_id] != device.confirmed_w
            or device.pending_command_id is not None
        )
    ]
    if changes:
        async with SessionFactory() as db, db.begin():
            config = await db.get(StationPower, station_id)
            assert config is not None
            config.state = "applying"
        # Reductions and reconciliation of uncertain intents precede EVERY increase.
        reductions = [d for d in changes if targets[d.connector_id] <= d.reserved_w]
        increases = [d for d in changes if targets[d.connector_id] > d.reserved_w]
        if not await apply_phase(reductions, targets, station_id, generation):
            return
        async with SessionFactory() as db:
            config = await db.get(StationPower, station_id)
            assert config is not None
            if config.generation != generation:
                return
        if not await apply_phase(increases, targets, station_id, generation):
            return
    async with SessionFactory() as db, db.begin():
        config = await db.scalar(
            select(StationPower)
            .where(StationPower.station_id == station_id)
            .with_for_update()
        )
        assert config is not None
        if config.generation == generation:
            config.applied_limit_w = limit
            config.dirty_at = None
            config.issue = (
                "offline_budget_retained" if any(not d.online for d in inputs) else None
            )
            config.state = "degraded" if config.issue else "ready"


async def power_loop() -> None:
    while True:
        try:
            async with SessionFactory() as db:
                ids = list(
                    await db.scalars(
                        select(StationPower.station_id).where(StationPower.enabled)
                    )
                )
            await asyncio.gather(*(reconcile_station(station_id) for station_id in ids))
        except (SQLAlchemyError, OSError, ValueError):
            logger.error("power_scan_failed")
        await asyncio.sleep(1)
