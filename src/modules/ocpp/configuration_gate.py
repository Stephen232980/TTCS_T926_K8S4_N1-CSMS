from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ocpp.configuration_models import ConfigurationIntent


async def verified_heartbeat(db: AsyncSession, point_id: UUID, default: int) -> int:
    value = await db.scalar(
        select(ConfigurationIntent.value)
        .where(
            ConfigurationIntent.charge_point_id == point_id,
            ConfigurationIntent.key == "HeartbeatInterval",
            ConfigurationIntent.state == "verified",
        )
        .order_by(ConfigurationIntent.verified_at.desc())
        .limit(1)
    )
    return value if value is not None else default


async def reboot_heartbeat(db: AsyncSession, point_id: UUID) -> int | None:
    """Boot advertises an accepted pending value without marking it verified."""
    return cast(
        int | None,
        await db.scalar(
            select(ConfigurationIntent.value)
            .where(
                ConfigurationIntent.charge_point_id == point_id,
                ConfigurationIntent.key == "HeartbeatInterval",
                ConfigurationIntent.state.in_(["reboot_required", "resetting"]),
            )
            .limit(1)
        ),
    )


async def reset_pending(db: AsyncSession, point_id: UUID) -> bool:
    """Called while holding charger row lock, also taken by reset admission."""
    return (
        await db.scalar(
            select(ConfigurationIntent.id)
            .where(
                ConfigurationIntent.charge_point_id == point_id,
                ConfigurationIntent.reset_id.is_not(None),
                ConfigurationIntent.state.in_(["resetting", "reboot_required"]),
            )
            .limit(1)
        )
        is not None
    )
