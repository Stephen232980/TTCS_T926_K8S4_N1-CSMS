"""Driver-owned starts reuse ordinary card authorization and real transactions."""

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.driver_models import DriverStartRequest, DriverVirtualTag
from src.modules.charging.models import ChargingCard, ChargingSession
from src.modules.charging.service import du_so_du_de_sac, tag_hash
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import Role, User, UserRole
from src.modules.ocpp import control
from src.modules.ocpp.connection_registry import ocpp_connections
from src.modules.ocpp.control_models import ControlRequest
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import DriverWallet
from src.platform.database.session import SessionFactory

START_CONFIRMATION_SECONDS = 60


async def expire_start_requests(
    session: AsyncSession, now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    requests = (
        await session.scalars(
            select(DriverStartRequest)
            .where(
                DriverStartRequest.status.in_(["Pending", "Accepted"]),
                DriverStartRequest.lease_until <= now,
            )
            .with_for_update()
        )
    ).all()
    for request in requests:
        if request.status == "Pending":
            request.status = request.reply_status = "Timeout"
            request.reply_at = now
            await control.record_result(session, request.id, "Timeout", now)
        else:
            request.status = "StartNotConfirmed"
    await session.flush()
    return len(requests)


async def virtual_tag(session: AsyncSession, driver: User) -> str:
    tag = await session.get(DriverVirtualTag, driver.id)
    if tag is None:
        raw = secrets.token_urlsafe(15)
        card = ChargingCard(
            tag_hash=tag_hash(raw),
            tag_tail=raw[-4:],
            driver_id=driver.id,
            issuer_id=driver.id,
        )
        session.add(card)
        await session.flush()
        tag = DriverVirtualTag(driver_id=driver.id, card_id=card.id, id_tag=raw)
        session.add(tag)
        await session.flush()
    stored_card = await session.get(ChargingCard, tag.card_id)
    if (
        stored_card is None
        or stored_card.status != "active"
        or (
            stored_card.expires_at is not None
            and stored_card.expires_at <= datetime.now(UTC)
        )
    ):
        raise HTTPException(
            409, "Thẻ sạc của bạn không còn hoạt động. Vui lòng liên hệ hỗ trợ."
        )
    return tag.id_tag


def start_result(request: DriverStartRequest) -> dict[str, object]:
    status = request.status
    if status == "Accepted" and request.lease_until <= datetime.now(UTC):
        status = "StartNotConfirmed"
    return {
        "id": request.id,
        "status": status,
        "reply_status": request.reply_status,
        "session_id": request.session_id,
        "deadline": request.lease_until if status == "Accepted" else None,
    }


async def remote_start(
    driver_id: UUID,
    request_id: UUID,
    connector_id: UUID,
    *,
    authorization: AuthorizationEvidence | None = None,
) -> dict[str, object]:
    now = datetime.now(UTC)
    async with SessionFactory() as session, session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": request_id.int % (2**63 - 1)},
        )
        previous = await session.get(DriverStartRequest, request_id)
        if previous:
            if previous.driver_id != driver_id or previous.connector_id != connector_id:
                raise HTTPException(409, "Mã yêu cầu đã được dùng cho thao tác khác.")
            return start_result(previous)
        # All charger writes lock charger before connector, including OCPP dispatch.
        registered = await session.get(Connector, connector_id)
        if registered is None:
            raise HTTPException(404, "Không tìm thấy đầu nối.")
        charger = await session.scalar(
            select(ChargePoint)
            .where(ChargePoint.id == registered.charge_point_id)
            .with_for_update()
        )
        connector = await session.scalar(
            select(Connector)
            .where(Connector.id == connector_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        driver = await session.scalar(
            select(User).where(User.id == driver_id).with_for_update()
        )
        is_driver = await session.scalar(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == driver_id, Role.code == "driver")
        )
        if driver is None or driver.status != "active" or is_driver is None:
            raise HTTPException(403, "Tài khoản không có quyền bắt đầu sạc.")
        station = await session.get(Station, charger.station_id) if charger else None
        if (
            charger is None
            or connector is None
            or connector.archived_at is not None
            or charger.archived_at is not None
            or station is None
            or station.archived_at is not None
            or station.status != "active"
        ):
            raise HTTPException(409, "Trạm hoặc đầu nối hiện không khả dụng.")
        wallet = await session.scalar(
            select(DriverWallet)
            .where(DriverWallet.driver_id == driver_id)
            .with_for_update()
        )
        if wallet is None or not du_so_du_de_sac(wallet.balance_vnd, station):
            raise HTTPException(409, "Số dư ví không đủ để bắt đầu phiên sạc.")
        await expire_start_requests(session, now)
        lease = await session.scalar(
            select(DriverStartRequest.id).where(
                DriverStartRequest.status.in_(["Pending", "Accepted"]),
                or_(
                    DriverStartRequest.connector_id == connector_id,
                    DriverStartRequest.driver_id == driver_id,
                ),
            )
        )
        occupied = await session.scalar(
            select(ChargingSession.id).where(
                ChargingSession.ended_at.is_(None),
                or_(
                    ChargingSession.connector_id == connector_id,
                    ChargingSession.driver_id == driver_id,
                ),
            )
        )
        if lease is not None or occupied is not None:
            raise HTTPException(
                409,
                "Đầu nối đang bận hoặc bạn đã có phiên/yêu cầu đang chờ. Vui lòng kiểm tra phiên của bạn.",
            )
        if connector.status not in ("Available", "Preparing"):
            raise HTTPException(
                409,
                "Đầu nối đang bận, được đặt chỗ hoặc chưa sẵn sàng. Vui lòng chọn đầu nối khác.",
            )
        connection = await ocpp_connections.get(charger.code.strip().lower())
        online = (
            connection is not None
            and connection.boot_accepted
            and charger.last_seen_at is not None
            and charger.last_seen_at
            >= now - timedelta(seconds=charger.heartbeat_interval_seconds * 2)
        )
        status = "Pending" if online else "Offline"
        request = DriverStartRequest(
            id=request_id,
            driver_id=driver_id,
            connector_id=connector_id,
            charge_point_id=charger.id,
            created_at=now,
            status=status,
            reply_status=status,
            lease_until=now + timedelta(seconds=control.COMMAND_TIMEOUT + 1),
        )
        session.add(request)
        session.add(
            ControlRequest(
                id=request_id,
                actor_id=driver_id,
                actor_email=driver.email,
                charge_point_id=charger.id,
                charge_point_code=charger.code,
                transaction_id=None,
                action="RemoteStartTransaction",
                permission=authorization.permission if authorization else None,
                actor_roles=list(authorization.roles) if authorization else None,
                payload={"connectorId": connector.connector_number},
                created_at=now,
            )
        )
        await session.flush()
        if not online:
            await control.record_result(session, request_id, "Offline", now)
            return start_result(request)
        raw_tag = await virtual_tag(session, driver)
        wire_payload: dict[str, object] = {
            "connectorId": connector.connector_number,
            "idTag": raw_tag,
        }
    assert connection is not None
    outcome = await control.send_command(
        connection, request_id, "RemoteStartTransaction", wire_payload
    )
    async with SessionFactory() as session, session.begin():
        completed = await session.scalar(
            select(DriverStartRequest)
            .where(DriverStartRequest.id == request_id)
            .with_for_update()
        )
        assert completed is not None
        received = datetime.now(UTC)
        # A real StartTransaction may race and precede the CALLRESULT.
        if completed.reply_status == "Pending":
            await control.record_result(session, request_id, outcome, received)
            outcome = await control.command_status(session, request_id)
            completed.reply_status = outcome
            completed.reply_at = received
            if completed.status != "Started":
                completed.status = outcome
                completed.lease_until = (
                    received + timedelta(seconds=START_CONFIRMATION_SECONDS)
                    if outcome == "Accepted"
                    else received
                )
        return start_result(completed)


async def attach_remote_start(
    session: AsyncSession, transaction: ChargingSession, card: ChargingCard | None
) -> None:
    if card is None or transaction.authorization_status != "Accepted":
        return
    tag = await session.scalar(
        select(DriverVirtualTag).where(DriverVirtualTag.card_id == card.id)
    )
    if tag is None:
        return
    request = await session.scalar(
        select(DriverStartRequest)
        .where(
            DriverStartRequest.driver_id == transaction.driver_id,
            DriverStartRequest.connector_id == transaction.connector_id,
            DriverStartRequest.session_id.is_(None),
            DriverStartRequest.status.in_(
                ["Pending", "Accepted", "StartNotConfirmed", "Timeout", "Disconnected"]
            ),
        )
        .order_by(DriverStartRequest.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if request is not None:
        request.session_id = transaction.id
        request.status = "Started"
        request.lease_until = datetime.now(UTC)


async def driver_start_loop() -> None:
    while True:
        try:
            async with SessionFactory() as session, session.begin():
                await expire_start_requests(session)
        except SQLAlchemyError:
            logging.getLogger("csms.ocpp").error("driver_start_scan_failed")
        await asyncio.sleep(1)
