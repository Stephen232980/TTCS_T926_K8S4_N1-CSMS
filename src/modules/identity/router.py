from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.identity.repository import IdentityRepository
from src.modules.identity.schemas import LoginRequest, LoginResponse
from src.modules.identity.service import (
    AuthService,
    InvalidCredentialsError,
    LoginLockedError,
)
from src.platform.database.session import get_db_session

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]

SESSION_COOKIE_NAME = "session"


def build_auth_service(db_session: AsyncSession) -> AuthService:
    return AuthService(
        db_session,
        IdentityRepository(db_session),
        max_failed_attempts=settings.auth_max_failed_attempts,
        lock_seconds=settings.auth_lock_seconds,
        session_ttl_seconds=settings.auth_session_ttl_seconds,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db_session: DatabaseSession,
) -> LoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    service = build_auth_service(db_session)

    try:
        result = await service.login(
            email=str(payload.email),
            password=payload.password.get_secret_value(),
            ip_address=client_ip,
        )
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng",
        ) from error
    except LoginLockedError as error:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Đăng nhập tạm thời bị khóa",
        ) from error

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=result.token,
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )

    return LoginResponse()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db_session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias=SESSION_COOKIE_NAME),
    ] = None,
) -> None:
    service = build_auth_service(db_session)
    await service.logout(session_token)

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
