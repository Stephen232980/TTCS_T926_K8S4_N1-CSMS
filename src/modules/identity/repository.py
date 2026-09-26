from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.models import LoginIpAttempt, Session, User


class IdentityRepository:
    def __init__(self, db_session: AsyncSession) -> None:
        self._db_session = db_session

    async def get_user_for_update(self, email: str) -> User | None:
        statement = select(User).where(User.email == email).with_for_update()
        result = await self._db_session.execute(statement)
        return result.scalar_one_or_none()

    async def get_ip_attempt_for_update(
        self,
        ip_address: str,
    ) -> LoginIpAttempt | None:
        statement = (
            select(LoginIpAttempt)
            .where(LoginIpAttempt.ip_address == ip_address)
            .with_for_update()
        )
        result = await self._db_session.execute(statement)
        return result.scalar_one_or_none()

    def add_ip_attempt(self, ip_attempt: LoginIpAttempt) -> None:
        self._db_session.add(ip_attempt)

    def add_session(self, login_session: Session) -> None:
        self._db_session.add(login_session)

    async def delete_session_by_token_hash(self, token_hash: str) -> None:
        statement = delete(Session).where(Session.token_hash == token_hash)
        await self._db_session.execute(statement)
