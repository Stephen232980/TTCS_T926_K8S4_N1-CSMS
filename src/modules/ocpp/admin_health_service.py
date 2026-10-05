import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, distinct, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.models import ChargingSession
from src.modules.ocpp.admin_health_models import OcppTelemetryBucket, SystemHealthSample
from src.modules.ocpp.telemetry import (
    RETENTION_HOURS,
    TelemetryBuffer,
    bucket_time,
    ocpp_telemetry,
)
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.health")


async def capture_sample(db: AsyncSession, now: datetime) -> None:
    boundary = bucket_time(now)
    since = boundary - timedelta(minutes=5)
    online = (
        (Station.status != "blocked")
        & (ChargePoint.status == "online")
        & ChargePoint.last_boot_at.is_not(None)
        & ChargePoint.last_seen_at.is_not(None)
        & (ChargePoint.last_seen_at <= now)
        & (
            ChargePoint.last_seen_at
            + ChargePoint.heartbeat_interval_seconds * text("INTERVAL '2 seconds'")
            >= now
        )
    )
    registered, online_count = (
        await db.execute(
            select(
                func.count(ChargePoint.id), func.count(ChargePoint.id).filter(online)
            )
            .join(Station)
            .where(ChargePoint.archived_at.is_(None), Station.archived_at.is_(None))
        )
    ).one()
    running = await db.scalar(
        select(func.count(ChargingSession.id))
        .join(ChargePoint)
        .join(Station)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .where(
            ChargingSession.ended_at.is_(None),
            ChargingSession.abnormal_since.is_(None),
            ChargingSession.started_at <= now,
            ChargePoint.archived_at.is_(None),
            Station.archived_at.is_(None),
            Connector.archived_at.is_(None),
            Connector.raw_ocpp_status == "Charging",
            Connector.status == "Charging",
            online,
        )
    )
    errors, responses, latency_total, covered = (
        await db.execute(
            select(
                func.coalesce(func.sum(OcppTelemetryBucket.error_count), 0),
                func.coalesce(func.sum(OcppTelemetryBucket.response_count), 0),
                func.coalesce(func.sum(OcppTelemetryBucket.latency_total_ms), 0),
                func.count(distinct(OcppTelemetryBucket.timestamp)).filter(
                    OcppTelemetryBucket.complete
                ),
            ).where(
                OcppTelemetryBucket.timestamp >= since,
                OcppTelemetryBucket.timestamp < boundary,
            )
        )
    ).one()
    complete = covered == 10
    values = {
        "timestamp": boundary,
        "collected_at": now,
        "registered_charge_points": registered,
        "online_charge_points": online_count,
        "running_sessions": running or 0,
        "error_messages_observed_5m": errors,
        "error_messages_5m": errors if complete else None,
        "response_count_5m": responses,
        "response_latency_ms": latency_total / responses if responses else None,
        "window_complete": complete,
    }
    statement = insert(SystemHealthSample).values(**values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[SystemHealthSample.timestamp],
            set_={key: value for key, value in values.items() if key != "timestamp"},
            where=SystemHealthSample.collected_at <= now,
        )
    )


async def collect_health(
    *, now: datetime | None = None, buffer: TelemetryBuffer = ocpp_telemetry
) -> None:
    now = now or datetime.now(UTC)
    buckets = buffer.snapshot(now)
    async with SessionFactory() as db, db.begin():
        if buckets:
            rows = [
                {
                    "timestamp": b.timestamp,
                    "worker_id": buffer.worker_id,
                    "error_count": b.error_count,
                    "response_count": b.response_count,
                    "latency_total_ms": b.latency_total_ms,
                    "complete": b.complete,
                }
                for b in buckets
            ]
            statement = insert(OcppTelemetryBucket).values(rows)
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        OcppTelemetryBucket.timestamp,
                        OcppTelemetryBucket.worker_id,
                    ],
                    set_={
                        key: getattr(statement.excluded, key)
                        for key in (
                            "error_count",
                            "response_count",
                            "latency_total_ms",
                            "complete",
                        )
                    },
                )
            )
        # One sampler writes network observations at a time; telemetry is per process.
        acquired = await db.scalar(text("SELECT pg_try_advisory_xact_lock(630005)"))
        if acquired:
            await capture_sample(db, now)
            cutoff = now - timedelta(hours=RETENTION_HOURS)
            await db.execute(
                delete(SystemHealthSample).where(SystemHealthSample.timestamp < cutoff)
            )
            await db.execute(
                delete(OcppTelemetryBucket).where(
                    OcppTelemetryBucket.timestamp < cutoff
                )
            )
    # A failed commit keeps dirty counters. Absolute-value upsert makes retries idempotent.
    buffer.acknowledge(buckets)


async def health_loop() -> None:
    import asyncio

    while True:
        try:
            await collect_health()
        except SQLAlchemyError:
            logger.error("system_health_collection_failed")
        await asyncio.sleep(30)
