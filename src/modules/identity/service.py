from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.models import LoginIpAttempt, Session, User
from src.modules.identity.repository import IdentityRepository
from src.modules.identity.security import (
    generate_session_token,
    hash_session_token,
    verify_dummy_password,
    verify_password,
)


class InvalidCredentialsError(Exception):
    """Email hoặc mật khẩu không hợp lệ."""


class LoginLockedError(Exception):
    """Tài khoản hoặc địa chỉ IP đang bị khóa tạm thời."""


@dataclass(frozen=True)
class LoginResult:
    token: str
    expires_at: datetime


class AuthService:
    def __init__(
        self,
        db_session: AsyncSession,
        repository: IdentityRepository,
        *,
        max_failed_attempts: int,
        lock_seconds: int,
        session_ttl_seconds: int,
    ) -> None:
        self._db_session = db_session
        self._repository = repository
        self._max_failed_attempts = max_failed_attempts
        self._lock_duration = timedelta(seconds=lock_seconds)
        self._session_ttl = timedelta(seconds=session_ttl_seconds)

    async def login(
        self,
        email: str,
        password: str,
        ip_address: str,
        *,
        now: datetime | None = None,
    ) -> LoginResult:
        current_time = now or datetime.now(UTC)
        normalized_email = email.strip().lower()

        user = await self._repository.get_user_for_update(normalized_email)
        ip_attempt = await self._repository.get_ip_attempt_for_update(ip_address)

        password_is_valid = self._verify_login_password(user, password)

        if self._is_login_locked(user, ip_attempt, current_time):
            await self._db_session.rollback()
            raise LoginLockedError

        if user is None or not password_is_valid:
            self._record_failed_attempt(
                user,
                ip_attempt,
                ip_address,
                current_time,
            )
            await self._db_session.commit()
            raise InvalidCredentialsError

        self._reset_failed_attempts(user, ip_attempt)

        token = generate_session_token()
        expires_at = current_time + self._session_ttl

        self._repository.add_session(
            Session(
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=expires_at,
            )
        )
        await self._db_session.commit()

        return LoginResult(token=token, expires_at=expires_at)

    async def logout(self, token: str | None) -> None:
        if token is None:
            return

        token_hash = hash_session_token(token)
        await self._repository.delete_session_by_token_hash(token_hash)
        await self._db_session.commit()

    @staticmethod
    def _verify_login_password(
        user: User | None,
        password: str,
    ) -> bool:
        if user is None:
            verify_dummy_password(password)
            return False

        return verify_password(user.password_hash, password)

    @staticmethod
    def _is_locked_until(
        locked_until: datetime | None,
        current_time: datetime,
    ) -> bool:
        return locked_until is not None and locked_until > current_time

    def _is_login_locked(
        self,
        user: User | None,
        ip_attempt: LoginIpAttempt | None,
        current_time: datetime,
    ) -> bool:
        user_is_locked = user is not None and self._is_locked_until(
            user.locked_until, current_time
        )
        ip_is_locked = ip_attempt is not None and self._is_locked_until(
            ip_attempt.locked_until,
            current_time,
        )
        return user_is_locked or ip_is_locked

    def _record_failed_attempt(
        self,
        user: User | None,
        ip_attempt: LoginIpAttempt | None,
        ip_address: str,
        current_time: datetime,
    ) -> None:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= self._max_failed_attempts:
                user.locked_until = current_time + self._lock_duration

        if ip_attempt is None:
            ip_attempt = LoginIpAttempt(
                ip_address=ip_address,
                failed_login_count=1,
            )
            self._repository.add_ip_attempt(ip_attempt)
        else:
            ip_attempt.failed_login_count += 1

        if ip_attempt.failed_login_count >= self._max_failed_attempts:
            ip_attempt.locked_until = current_time + self._lock_duration

    @staticmethod
    def _reset_failed_attempts(
        user: User,
        ip_attempt: LoginIpAttempt | None,
    ) -> None:
        user.failed_login_count = 0
        user.locked_until = None

        if ip_attempt is not None:
            ip_attempt.failed_login_count = 0
            ip_attempt.locked_until = None
