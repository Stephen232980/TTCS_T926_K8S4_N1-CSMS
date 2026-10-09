"""OCPP transactions run inside the dispatcher's charger lock and replay transaction."""

import hashlib
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import case, literal, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.charging.meter_units import UNITS, numeric_sample
from src.modules.charging.models import (
    AuthorizationAttempt,
    ChargingCard,
    ChargingSession,
    ChargingSessionEvent,
    MeterSample,
    PendingChargingMessage,
)
from src.modules.charging.payloads import (
    AuthorizePayload,
    MeterBlock,
    MeterPayload,
    StartPayload,
    StopPayload,
)
from src.modules.identity.models import Role, User, UserRole
from src.modules.ocpp.frames import Frame
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.stations.repository import StationRepository
from src.modules.wallet.models import Wallet

logger = logging.getLogger("csms.ocpp")


def du_so_du_de_sac(wallet_balance_vnd: Decimal | int | None, station: Station) -> bool:
    price = station.price_vnd_per_kwh
    if wallet_balance_vnd is None or price is None or price <= 0:
        return False
    minimum_balance = (
        settings.charging_minimum_kwh * price + settings.wallet_reserve_vnd
    )
    return wallet_balance_vnd >= minimum_balance


def tag_hash(tag: str) -> str:
    return hashlib.sha256(tag.encode()).hexdigest()


def review(transaction: ChargingSession, reason: str) -> None:
    if reason not in transaction.review_reasons:
        transaction.review_reasons = [*transaction.review_reasons, reason]


async def authorize(
    session: AsyncSession, charger: ChargePoint, tag: str
) -> tuple[str, ChargingCard | None]:
    row = (
        await session.execute(
            select(ChargingCard, User.status)
            .join(User, User.id == ChargingCard.driver_id)
            .where(ChargingCard.tag_hash == tag_hash(tag))
        )
    ).first()
    card = row[0] if row else None
    station = await session.get(Station, charger.station_id, populate_existing=True)
    result = "Invalid"
    if card is not None:
        is_driver = await session.scalar(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == card.driver_id, Role.code == "driver")
        )
        if (
            card.status != "active"
            or row is None
            or row[1] != "active"
            or is_driver is None
        ):
            result = "Blocked"
        elif card.expires_at is not None and card.expires_at <= datetime.now(UTC):
            result = "Expired"
        else:
            result = "Accepted"
    if station is None or station.archived_at is not None or station.status != "active":
        result = "Blocked"
    if result == "Accepted" and card is not None and station is not None:
        wallet = await session.scalar(
            select(Wallet).where(Wallet.driver_id == card.driver_id)
        )
        if (
            wallet is None
            or wallet.status != "active"
            or not du_so_du_de_sac(wallet.balance_vnd, station)
        ):
            result = "Blocked"
    session.add(
        AuthorizationAttempt(
            charge_point_id=charger.id, tag_tail=tag[-4:], result=result
        )
    )
    if result != "Accepted":
        logger.warning(
            "ocpp_authorization charger=%s tag_tail=%s result=%s",
            charger.id,
            tag[-4:],
            result,
        )
    return result, card


def pending(
    session: AsyncSession, charger: ChargePoint, frame: Frame, reason: str
) -> None:
    # Never persist the raw identifying tag, even in reconciliation records.
    payload = {key: value for key, value in frame.payload.items() if key != "idTag"}
    session.add(
        PendingChargingMessage(
            charge_point_id=charger.id,
            action=frame.action or "",
            message_id=frame.message_id,
            reason=reason,
            payload=payload,
        )
    )
    logger.warning(
        "ocpp_charging_pending charger=%s action=%s reason=%s",
        charger.id,
        frame.action,
        reason,
    )


async def store_samples(
    session: AsyncSession,
    transaction: ChargingSession,
    blocks: Sequence[MeterBlock],
    *,
    backfill: bool = False,
    latest: dict[tuple[str, str, str], tuple[datetime, Decimal]] | None = None,
    history: dict[tuple[str, str, str], dict[datetime, Decimal]] | None = None,
) -> None:
    if backfill:
        await store_recovery_samples(session, transaction, blocks, history=history)
        return
    if latest is None:
        previous = (
            await session.scalars(
                select(MeterSample)
                .where(MeterSample.session_id == transaction.id)
                .distinct(
                    MeterSample.measurand, MeterSample.phase, MeterSample.location
                )
                .order_by(
                    MeterSample.measurand,
                    MeterSample.phase,
                    MeterSample.location,
                    MeterSample.timestamp.desc(),
                )
            )
        ).all()
        latest = {
            (item.measurand, item.phase, item.location): (item.timestamp, item.value)
            for item in previous
        }
    for block in blocks:
        for sample in block.sampledValue:
            numeric = numeric_sample(sample)
            if numeric is None:
                if sample.measurand in UNITS:
                    logger.warning(
                        "ocpp_meter_sample_ignored transaction=%s measurand=%s",
                        transaction.id,
                        sample.measurand,
                    )
                continue
            value, unit = numeric
            key = (sample.measurand, sample.phase, sample.location)
            old = latest.get(key)
            if old is None and key == ("Energy.Active.Import.Register", "", "Outlet"):
                old = (transaction.started_at, transaction.meter_start_wh)
            if old is not None:
                if block.timestamp < old[0]:
                    logger.warning(
                        "ocpp_meter_old_timestamp transaction=%s", transaction.id
                    )
                    continue
                if block.timestamp == old[0]:
                    if value != old[1]:
                        review(transaction, "conflicting_meter_timestamp")
                        logger.warning(
                            "ocpp_meter_conflicting_timestamp transaction=%s",
                            transaction.id,
                        )
                    continue
                if (
                    sample.measurand == "Energy.Active.Import.Register"
                    and value < old[1]
                ):
                    review(transaction, "meter_regression")
                    logger.warning(
                        "ocpp_meter_regression transaction=%s", transaction.id
                    )
            if block.timestamp < transaction.started_at:
                logger.warning("ocpp_meter_before_start transaction=%s", transaction.id)
                continue
            session.add(
                MeterSample(
                    session_id=transaction.id,
                    timestamp=block.timestamp,
                    measurand=sample.measurand,
                    phase=sample.phase,
                    location=sample.location,
                    value=value,
                    unit=unit,
                )
            )
            latest[key] = (block.timestamp, value)


async def store_recovery_samples(
    session: AsyncSession,
    transaction: ChargingSession,
    blocks: Sequence[MeterBlock],
    *,
    history: dict[tuple[str, str, str], dict[datetime, Decimal]] | None = None,
) -> None:
    """Late buffered samples retain their timestamps, including gaps before newest data."""
    if history is None:
        values = (
            await session.scalars(
                select(MeterSample).where(MeterSample.session_id == transaction.id)
            )
        ).all()
        history = {}
        for item in values:
            history.setdefault((item.measurand, item.phase, item.location), {})[
                item.timestamp
            ] = item.value
    series = history
    for block in sorted(blocks, key=lambda item: item.timestamp):
        if block.timestamp < transaction.started_at or (
            transaction.ended_at is not None and block.timestamp > transaction.ended_at
        ):
            continue
        for sample in block.sampledValue:
            numeric = numeric_sample(sample)
            if numeric is None:
                continue
            value, unit = numeric
            key = (sample.measurand, sample.phase, sample.location)
            points = series.setdefault(key, {})
            if block.timestamp in points:
                if points[block.timestamp] != value:
                    review(transaction, "conflicting_meter_timestamp")
                continue
            if sample.measurand == "Energy.Active.Import.Register":
                before = [stamp for stamp in points if stamp < block.timestamp]
                after = [stamp for stamp in points if stamp > block.timestamp]
                previous = (
                    points[max(before)]
                    if before
                    else transaction.meter_start_wh
                    if key == ("Energy.Active.Import.Register", "", "Outlet")
                    else None
                )
                following = points[min(after)] if after else None
                if (previous is not None and value < previous) or (
                    following is not None and value > following
                ):
                    review(transaction, "meter_regression")
            session.add(
                MeterSample(
                    session_id=transaction.id,
                    timestamp=block.timestamp,
                    measurand=sample.measurand,
                    phase=sample.phase,
                    location=sample.location,
                    value=value,
                    unit=unit,
                )
            )
            points[block.timestamp] = value


async def start_transaction(
    session: AsyncSession, charger: ChargePoint, frame: Frame, payload: StartPayload
) -> dict[str, object]:
    # Serialize the first session with station-timezone changes. The dispatcher
    # already locks the charger; keep charger -> station -> connector lock order.
    await session.scalar(
        select(Station.id).where(Station.id == charger.station_id).with_for_update()
    )
    connector = await session.scalar(
        select(Connector)
        .where(
            Connector.charge_point_id == charger.id,
            Connector.connector_number == payload.connectorId,
            Connector.archived_at.is_(None),
        )
        .with_for_update()
    )
    if connector is None:
        raise ValueError("Connector is not registered")
    result, card = await authorize(session, charger, payload.idTag)
    old = await session.scalar(
        select(ChargingSession)
        .where(
            ChargingSession.connector_id == connector.id,
            ChargingSession.ended_at.is_(None),
        )
        .with_for_update()
    )
    if old is not None:
        # Exact message replays are handled by the dispatcher's durable cache.
        # A masked tag suffix cannot establish that a new call is a replay.
        old.ended_at = datetime.now(UTC)
        old.stop_reason = "ReplacedByNewTransaction"
        review(old, "replaced_open_session")
        old.abnormal_since = None
        logger.warning(
            "ocpp_open_session_replaced transaction=%s charger=%s", old.id, charger.id
        )
        await session.flush()
    transaction = ChargingSession(
        charge_point_id=charger.id,
        connector_id=connector.id,
        driver_id=card.driver_id if card else None,
        tag_tail=payload.idTag[-4:],
        authorization_status=result,
        started_at=payload.timestamp,
        meter_start_wh=Decimal(payload.meterStart),
        review_reasons=[],
    )
    if result != "Accepted":
        review(transaction, "authorization_" + result.lower())
    if payload.meterStart < 0:
        review(transaction, "negative_start_meter")
    if old is not None:
        review(transaction, "replaced_open_session")
    if payload.reservationId is not None:
        review(transaction, "reservation_not_verified")
    session.add(transaction)
    await session.flush()
    await StationRepository(session).lock_charge_point_code_for_charging(
        charger.id, locked_at=datetime.now(UTC)
    )
    from src.modules.charging.driver import attach_remote_start

    await attach_remote_start(session, transaction, card)
    return {"transactionId": transaction.id, "idTagInfo": {"status": result}}


async def meter_values(
    session: AsyncSession, charger: ChargePoint, frame: Frame, payload: MeterPayload
) -> dict[str, object]:
    # Recovery needs every timestamp to validate buffered gaps; ordinary reports
    # need only the newest point per series. Fetch either in the same locked read.
    recovery_timestamp = (
        case((ChargingSession.recovery_at.is_not(None), MeterSample.timestamp))
        if payload.transactionId is not None
        else case((literal(False), MeterSample.timestamp))
    )
    latest_sample = (
        select(
            MeterSample.measurand,
            MeterSample.phase,
            MeterSample.location,
            MeterSample.timestamp,
            MeterSample.value,
        )
        .where(MeterSample.session_id == ChargingSession.id)
        .distinct(
            MeterSample.measurand,
            MeterSample.phase,
            MeterSample.location,
            recovery_timestamp,
        )
        .order_by(
            MeterSample.measurand,
            MeterSample.phase,
            MeterSample.location,
            recovery_timestamp,
            MeterSample.timestamp.desc(),
        )
        .lateral("latest_meter_sample")
    )
    statement = (
        select(ChargingSession, latest_sample)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .outerjoin(latest_sample, true())
        .where(
            ChargingSession.charge_point_id == charger.id,
            Connector.connector_number == payload.connectorId,
        )
    )
    if payload.transactionId is not None:
        statement = statement.where(ChargingSession.id == payload.transactionId)
    else:
        statement = statement.where(ChargingSession.ended_at.is_(None))
    rows = (await session.execute(statement.with_for_update(of=ChargingSession))).all()
    transaction = rows[0][0] if rows else None
    latest: dict[tuple[str, str, str], tuple[datetime, Decimal]] = {}
    history: dict[tuple[str, str, str], dict[datetime, Decimal]] = {}
    for row in rows:
        if row[1] is not None:
            key = (row[1], row[2], row[3])
            history.setdefault(key, {})[row[4]] = row[5]
            if key not in latest or row[4] > latest[key][0]:
                latest[key] = (row[4], row[5])
    if (
        transaction is None
        or transaction.manual_closed_at is not None
        or (transaction.ended_at is not None and transaction.recovery_at is None)
    ):
        pending(session, charger, frame, "no_matching_open_session")
    else:
        await store_samples(
            session,
            transaction,
            payload.meterValue,
            latest=latest,
            history=history,
            backfill=payload.transactionId is not None
            and transaction.recovery_at is not None,
        )
    return {}


async def stop_transaction(
    session: AsyncSession, charger: ChargePoint, frame: Frame, payload: StopPayload
) -> dict[str, object]:
    transaction = await session.scalar(
        select(ChargingSession)
        .where(
            ChargingSession.id == payload.transactionId,
            ChargingSession.charge_point_id == charger.id,
        )
        .with_for_update()
    )
    if transaction is None or transaction.ended_at is not None:
        pending(
            session,
            charger,
            frame,
            "unknown_transaction"
            if transaction is None
            else "already_closed_transaction",
        )
        return {}
    was_abnormal = transaction.abnormal_since is not None
    transaction.meter_stop_wh = Decimal(payload.meterStop)
    transaction.ended_at = payload.timestamp
    transaction.stop_reason = payload.reason
    await store_samples(
        session,
        transaction,
        payload.transactionData,
        backfill=transaction.recovery_at is not None,
    )
    latest_meter = await session.scalar(
        select(MeterSample.value)
        .where(
            MeterSample.session_id == transaction.id,
            MeterSample.measurand == "Energy.Active.Import.Register",
            MeterSample.phase == "",
            MeterSample.location == "Outlet",
            MeterSample.unit == "Wh",
            MeterSample.timestamp >= transaction.started_at,
            MeterSample.timestamp <= payload.timestamp,
        )
        .order_by(MeterSample.timestamp.desc(), MeterSample.id.desc())
        .limit(1)
    )
    if latest_meter is not None and payload.meterStop < latest_meter:
        review(transaction, "stop_meter_below_latest")
        logger.warning("ocpp_stop_meter_below_latest transaction=%s", transaction.id)
    transaction.abnormal_since = None
    transaction.review_reasons = [
        reason
        for reason in transaction.review_reasons
        if reason
        not in (
            "offline_timeout",
            "available_with_open_session",
            "remote_stop_not_confirmed",
        )
    ]
    if was_abnormal or transaction.recovery_at is not None:
        session.add(
            ChargingSessionEvent(
                session_id=transaction.id,
                action="late_stop",
                details={
                    "meter_stop_wh": str(payload.meterStop),
                    "ended_at": payload.timestamp.isoformat(),
                },
            )
        )
    if payload.timestamp < transaction.started_at:
        review(transaction, "stop_before_start")
    if (
        payload.meterStop < transaction.meter_start_wh
        or payload.meterStop < 0
        or transaction.meter_start_wh < 0
    ):
        review(transaction, "stop_meter_below_start")
        transaction.energy_kwh = None
    elif payload.timestamp >= transaction.started_at:
        transaction.energy_kwh = (
            Decimal(payload.meterStop) - transaction.meter_start_wh
        ) / Decimal(1000)
    return {}


async def charging_call(
    session: AsyncSession, charger: ChargePoint, frame: Frame
) -> dict[str, object]:
    if any(value is None for value in frame.payload.values()):
        raise ValueError("Null OCPP property")
    import json

    raw = json.dumps(frame.payload)
    if frame.action == "Authorize":
        payload = AuthorizePayload.model_validate_json(raw)
        result, _ = await authorize(session, charger, payload.idTag)
        return {"idTagInfo": {"status": result}}
    if frame.action == "StartTransaction":
        return await start_transaction(
            session, charger, frame, StartPayload.model_validate_json(raw)
        )
    if frame.action == "MeterValues":
        return await meter_values(
            session, charger, frame, MeterPayload.model_validate_json(raw)
        )
    return await stop_transaction(
        session, charger, frame, StopPayload.model_validate_json(raw)
    )
