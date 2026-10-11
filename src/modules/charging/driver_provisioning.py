"""Provision private charging identity and wallet together, without committing."""

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.driver_models import DriverVirtualTag
from src.modules.charging.models import ChargingCard
from src.modules.charging.service import tag_hash
from src.modules.identity.models import User
from src.modules.wallet.provisioning import ensure_driver_wallet


async def ensure_driver_resources(
    session: AsyncSession, driver: User
) -> DriverVirtualTag:
    # Wallet creation locks the user, serializing concurrent tag creation as well.
    await ensure_driver_wallet(session, driver.id)
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
    return tag
