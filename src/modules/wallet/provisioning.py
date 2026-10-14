"""Create a driver's zero wallet once; caller owns the account transaction."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.models import Role, User, UserRole
from src.modules.wallet.exceptions import WalletError
from src.modules.wallet.models import Wallet


class WalletDriverRequiredError(WalletError):
    pass


async def ensure_driver_wallet(session: AsyncSession, driver_id: UUID) -> Wallet:
    user = await session.scalar(
        select(User).where(User.id == driver_id).with_for_update()
    )
    driver = await session.scalar(
        select(UserRole.user_id)
        .join(Role)
        .where(UserRole.user_id == driver_id, Role.code == "driver")
    )
    if user is None or driver is None:
        raise WalletDriverRequiredError("An account with the driver role is required")
    wallet: Wallet | None = await session.scalar(
        insert(Wallet)
        .values(id=uuid4(), driver_id=driver_id, balance_vnd=0, status="active")
        .on_conflict_do_nothing(constraint="uq_wallets_driver")
        .returning(Wallet)
    )
    if wallet is None:
        wallet = await session.scalar(
            select(Wallet).where(Wallet.driver_id == driver_id)
        )
    if wallet is None:
        raise WalletDriverRequiredError(
            "Wallet winner unavailable; roll back and retry"
        )
    return wallet
