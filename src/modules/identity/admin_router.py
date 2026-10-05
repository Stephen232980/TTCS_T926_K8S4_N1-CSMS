from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.admin_schemas import (
    AccountCreateRequest,
    AccountListQuery,
    AccountListResponse,
    AccountResponse,
    AccountUpdateRequest,
    RoleResponse,
)
from src.modules.identity.admin_service import AdminAccountService
from src.modules.identity.authorization import allow_roles
from src.modules.identity.dependencies import CurrentActorDependency, authorize_request
from src.platform.database.session import get_db_session


class AdminAccountRoute(APIRoute):
    """Scoped error contract; validation must never echo a supplied password."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                result = await handler(request)
                result.headers["Cache-Control"] = "no-store"
                return result
            except (HTTPException, RequestValidationError) as exc:
                fields: list[dict[str, str]] = []
                if isinstance(exc, RequestValidationError):
                    status_code, code, message = (
                        422,
                        "validation_error",
                        "Dữ liệu không hợp lệ",
                    )
                    fields = [
                        {
                            "field": ".".join(str(v) for v in e["loc"][1:]),
                            "code": str(e["type"]),
                            "message": str(e["msg"]),
                        }
                        for e in exc.errors()
                    ]
                else:
                    status_code = exc.status_code
                    code = {
                        401: "authentication_required",
                        403: "permission_denied",
                        404: "resource_not_found",
                        409: "resource_conflict",
                        422: "validation_error",
                    }.get(status_code, "bad_request")
                    message = str(exc.detail)
                return JSONResponse(
                    status_code=status_code,
                    headers={"Cache-Control": "no-store"},
                    content={
                        "error": {
                            "code": code,
                            "message": message,
                            "fields": fields,
                            "request_id": None,
                        }
                    },
                )

        return safe_handler


router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-accounts"],
    dependencies=[Depends(authorize_request)],
    route_class=AdminAccountRoute,
)
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
AccountListQueryDependency = Annotated[AccountListQuery, Query()]


@router.get("/roles", response_model=list[RoleResponse])
@allow_roles("admin")
async def list_roles(db_session: DatabaseSession) -> list[RoleResponse]:
    return await AdminAccountService(db_session).roles()


@router.get("/accounts", response_model=AccountListResponse)
@allow_roles("admin")
async def list_accounts(
    query: AccountListQueryDependency, db_session: DatabaseSession
) -> AccountListResponse:
    return await AdminAccountService(db_session).list_accounts(query)


@router.get("/accounts/{user_id}", response_model=AccountResponse)
@allow_roles("admin")
async def get_account(user_id: UUID, db_session: DatabaseSession) -> AccountResponse:
    return await AdminAccountService(db_session).detail(user_id)


@router.post("/accounts", response_model=AccountResponse, status_code=201)
@allow_roles("admin")
async def create_account(
    payload: AccountCreateRequest,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> AccountResponse:
    return await AdminAccountService(db_session).create(payload, actor)


@router.patch("/accounts/{user_id}", response_model=AccountResponse)
@allow_roles("admin")
async def update_account(
    user_id: UUID,
    payload: AccountUpdateRequest,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> AccountResponse:
    return await AdminAccountService(db_session).change(user_id, payload, actor)
