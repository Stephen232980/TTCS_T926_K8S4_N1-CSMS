from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import CurrentActor
from src.modules.identity.models import (
    LoginIpAttempt,
    Role,
    Session,
    User,
    UserRole,
)


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

    async def get_current_actor_by_session_hash(
        self,
        token_hash: str,
        current_time: datetime,
    ) -> CurrentActor | None:
        statement = (
            select(User.id, Role.code)
            .join(Session, Session.user_id == User.id)
            .outerjoin(UserRole, UserRole.user_id == User.id)
            .outerjoin(Role, Role.id == UserRole.role_id)
            .where(
                Session.token_hash == token_hash,
                Session.expires_at > current_time,
            )
        )
        rows = (await self._db_session.execute(statement)).all()

        if not rows:
            return None

        user_id = rows[0][0]
        roles = frozenset(role_code for _, role_code in rows if role_code is not None)
        return CurrentActor(user_id=user_id, roles=roles)
