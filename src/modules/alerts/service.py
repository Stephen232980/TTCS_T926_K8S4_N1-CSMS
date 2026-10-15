"""Read-only alert views and a serialized, persistent incident scanner."""

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.alerts.models import AlertEmail, AlertRuleState, OperationalAlert
from src.modules.identity.authorization import ActorScope, AuthorizationEvidence
from src.modules.ocpp.monitoring import database_time
from src.modules.stations.models import ChargePoint, Connector, ConnectorError, Station
from src.platform.audit.service import ghi_nhat_ky
from src.platform.email import smtp_enabled

ACTIVE = ("open", "acknowledged")


def live(point: ChargePoint, now: datetime) -> bool:
    return bool(
        point.status == "online"
        and point.last_boot_at
        and point.last_seen_at
        and point.last_seen_at <= now
        and now - point.last_seen_at
        <= timedelta(seconds=2 * point.heartbeat_interval_seconds)
    )


def queue_email(db: AsyncSession, alert: OperationalAlert, now: datetime) -> None:
    for recipient in sorted({str(value) for value in settings.alert_email_recipients}):
        db.add(AlertEmail(alert_id=alert.id, recipient=recipient, next_attempt_at=now))


async def scan_alerts(db: AsyncSession, now: datetime | None = None) -> int:
    if not await db.scalar(text("SELECT pg_try_advisory_xact_lock(46, 63)")):
        return 0
    now = now or await database_time(db)
    points = list(
        await db.scalars(
            select(ChargePoint)
            .join(Station)
            .where(
                ChargePoint.archived_at.is_(None),
                Station.archived_at.is_(None),
                Station.status != "blocked",
            )
        )
    )
    states = {
        row.charge_point_id: row
        for row in await db.scalars(select(AlertRuleState).with_for_update())
    }
    active = {
        row.charge_point_id: row
        for row in await db.scalars(
            select(OperationalAlert)
            .where(OperationalAlert.status.in_(ACTIVE))
            .with_for_update()
        )
    }
    error_window = timedelta(seconds=settings.alert_error_window_seconds)
    error_rows = (
        await db.execute(
            select(
                Connector.charge_point_id,
                func.count(ConnectorError.id).filter(
                    ConnectorError.occurred_at >= now - error_window
                ),
                func.max(ConnectorError.occurred_at),
            )
            .join(ConnectorError, ConnectorError.connector_id == Connector.id)
            .where(Connector.archived_at.is_(None), ConnectorError.occurred_at <= now)
            .group_by(Connector.charge_point_id)
        )
    ).all()
    errors = {row[0]: (int(row[1]), row[2]) for row in error_rows}
    opened = 0
    for point in points:
        state = states.get(point.id)
        if state is None:
            state = AlertRuleState(
                charge_point_id=point.id, armed=True, recovery_observations=0
            )
            db.add(state)
        online = live(point, now)
        if online:
            if state.online_since is None:
                state.online_since = now
                state.recovery_observations = 0
            if state.recovery_last_seen != point.last_seen_at:
                state.recovery_observations += 1
                state.recovery_last_seen = point.last_seen_at
        else:
            state.online_since = None
            state.recovery_last_seen = None
            state.recovery_observations = 0
        count, latest_error = errors.get(point.id, (0, None))
        quiet = latest_error is None or latest_error <= now - error_window
        recovered = bool(
            online
            and state.online_since
            and now - state.online_since
            >= timedelta(seconds=2 * point.heartbeat_interval_seconds)
            and state.recovery_observations >= 2
            and quiet
        )
        reference = point.last_seen_at or point.created_at
        offline_late = bool(
            not online
            and reference
            and now - reference
            >= timedelta(
                seconds=2 * point.heartbeat_interval_seconds
                + settings.alert_offline_grace_seconds
            )
        )
        trigger = offline_late or count >= settings.alert_error_threshold
        alert = active.get(point.id)
        if recovered:
            state.armed = True
            if alert and alert.recovered_at is None:
                alert.recovered_at = now
        elif alert:
            alert.recovered_at = None
        if trigger:
            if state.armed and alert is None:
                alert = OperationalAlert(
                    charge_point_id=point.id,
                    kind="offline" if offline_late else "error_burst",
                    opened_at=now,
                    details={
                        "error_count": count,
                        "error_window_seconds": settings.alert_error_window_seconds,
                        "offline_grace_seconds": settings.alert_offline_grace_seconds,
                        "heartbeat_interval_seconds": point.heartbeat_interval_seconds,
                    },
                )
                db.add(alert)
                await db.flush()
                queue_email(db, alert, now)
                opened += 1
            state.armed = False
    await db.flush()
    return opened


async def alert_list(
    db: AsyncSession, scope: ActorScope, status: str, page: int
) -> dict[str, object]:
    statement = (
        select(OperationalAlert, ChargePoint.code, Station.name)
        .join(ChargePoint, ChargePoint.id == OperationalAlert.charge_point_id)
        .join(Station, Station.id == ChargePoint.station_id)
        .where(ChargePoint.archived_at.is_(None), Station.archived_at.is_(None))
    )
    if scope.owner_id is not None:
        statement = statement.where(Station.owner_id == scope.owner_id)
    if status == "active":
        statement = statement.where(OperationalAlert.status.in_(ACTIVE))
    elif status != "all":
        statement = statement.where(OperationalAlert.status == status)
    total = int(
        await db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    page = min(page, max(1, (total + 49) // 50))
    rows = (
        await db.execute(
            statement.order_by(OperationalAlert.opened_at.desc(), OperationalAlert.id)
            .offset((page - 1) * 50)
            .limit(50)
        )
    ).all()
    emails: dict[UUID, list[AlertEmail]] = {}
    if rows:
        for email in await db.scalars(
            select(AlertEmail).where(
                AlertEmail.alert_id.in_([row[0].id for row in rows])
            )
        ):
            emails.setdefault(email.alert_id, []).append(email)
    items = []
    for alert, code, name in rows:
        deliveries = emails.get(alert.id, [])
        delivery_state = (
            "unconfigured"
            if not deliveries
            or not settings.alert_smtp_enabled
            or not smtp_enabled(settings)
            else (
                "sent"
                if all(email.status == "sent" for email in deliveries)
                else "failed"
                if any(email.status == "failed" for email in deliveries)
                else "retry"
                if any(email.status == "retry" for email in deliveries)
                else "pending"
            )
        )
        items.append(
            {
                "id": str(alert.id),
                "charge_point_id": str(alert.charge_point_id),
                "charge_point_code": code,
                "station_name": name,
                "kind": alert.kind,
                "status": alert.status,
                "opened_at": alert.opened_at,
                "acknowledged_at": alert.acknowledged_at,
                "closed_at": alert.closed_at,
                "close_reason": alert.close_reason,
                "recovered_at": alert.recovered_at,
                "email_status": delivery_state,
                "email_attempts": max((e.attempts for e in deliveries), default=0),
            }
        )
    return {
        "items": items,
        "total": total,
        "page": page,
        "total_pages": (total + 49) // 50,
        "generated_at": await database_time(db),
        "refresh_after_seconds": 10,
    }


async def mutate_alert(
    db: AsyncSession,
    alert_id: UUID,
    action: str,
    scope: ActorScope,
    evidence: AuthorizationEvidence,
    *,
    force: bool = False,
    reason: str = "",
) -> None:
    alert = await db.scalar(
        select(OperationalAlert)
        .join(ChargePoint)
        .join(Station)
        .where(
            OperationalAlert.id == alert_id,
            Station.archived_at.is_(None),
            ChargePoint.archived_at.is_(None),
        )
        .with_for_update(of=OperationalAlert)
    )
    if alert is None:
        raise HTTPException(404, "resource_not_found")
    now = await database_time(db)
    before = alert.status
    if action == "acknowledge":
        if alert.status == "closed":
            raise HTTPException(409, "alert_already_closed")
        if alert.status == "acknowledged":
            return
        alert.status, alert.acknowledged_at, alert.acknowledged_by = (
            "acknowledged",
            now,
            scope.actor_id,
        )
    elif action == "close":
        if force and "admin" not in evidence.roles:
            raise HTTPException(403, "permission_denied")
        if force and not reason.strip():
            raise HTTPException(422, "alert_close_reason_required")
        if alert.status == "closed":
            return
        if not force and alert.recovered_at is None:
            raise HTTPException(409, "alert_not_recovered")
        if not force:
            point = await db.get(ChargePoint, alert.charge_point_id)
            latest = await db.scalar(
                select(func.max(ConnectorError.occurred_at))
                .join(Connector, Connector.id == ConnectorError.connector_id)
                .where(
                    Connector.charge_point_id == alert.charge_point_id,
                    ConnectorError.occurred_at <= now,
                )
            )
            if (
                point is None
                or not live(point, now)
                or (
                    latest is not None
                    and latest
                    > now - timedelta(seconds=settings.alert_error_window_seconds)
                )
            ):
                raise HTTPException(409, "alert_not_recovered")
        alert.status, alert.closed_at, alert.closed_by = "closed", now, scope.actor_id
        alert.close_reason = reason.strip() or "recovered"
    elif action == "retry-email":
        if not settings.alert_smtp_enabled or not smtp_enabled(settings):
            raise HTTPException(409, "alert_email_not_configured")
        rows = list(
            await db.scalars(
                select(AlertEmail)
                .where(AlertEmail.alert_id == alert.id)
                .with_for_update()
            )
        )
        if not rows:
            queue_email(db, alert, now)
        changed = not rows
        for email in rows:
            if email.status == "failed":
                (
                    email.status,
                    email.next_attempt_at,
                    email.attempts,
                    email.last_error,
                ) = "pending", now, 0, None
                changed = True
        if not changed:
            return
    else:
        raise ValueError("Unknown alert mutation")
    await ghi_nhat_ky(
        db,
        actor_id=scope.actor_id,
        action=f"alert.{action}",
        object_type="alert",
        object_id=str(alert.id),
        data={"before": before, "after": alert.status, "reason": alert.close_reason},
        permission=evidence.permission,
        actor_roles=evidence.roles,
    )
