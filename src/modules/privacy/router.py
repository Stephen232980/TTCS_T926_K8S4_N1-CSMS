from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    AuditEvidence,
    CurrentActorDependency,
    authorize_request,
)
from src.modules.identity.models import User
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.privacy.schemas import (
    AnonymizeUserRequest,
    AnonymizeUserResponse,
    DriverPrivacyRequest,
    LegalHoldRequest,
    LegalHoldResponse,
    PrivacyDecision,
    PrivacyReceipt,
    RetentionCleanupResponse,
    RetentionPoliciesResponse,
)
from src.modules.privacy.service import PrivacyRetentionService
from src.platform.database.session import get_db_session


class AdminPrivacyRoute(PolicyRoute):
    """Scoped error contract for admin privacy and retention operations."""

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
                        "Dá»¯ liá»‡u khÃ´ng há»£p lá»‡",
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
    prefix="/api/v1/admin/privacy",
    tags=["admin-privacy"],
    dependencies=[Depends(authorize_request)],
    route_class=AdminPrivacyRoute,
)

driver_router = APIRouter(
    prefix="/api/v1/driver/privacy",
    tags=["driver-privacy"],
    dependencies=[Depends(authorize_request)],
    route_class=AdminPrivacyRoute,
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/retention-policies", response_model=RetentionPoliciesResponse)
@user_policy("admin.privacy.view", "all", "admin")
async def get_retention_policies(
    db_session: DatabaseSession,
) -> RetentionPoliciesResponse:
    return await PrivacyRetentionService(db_session).get_retention_policies()


@router.post("/cleanup", response_model=RetentionCleanupResponse)
@user_policy("admin.privacy.manage", "all", "admin")
async def execute_retention_cleanup(
    actor: CurrentActorDependency,
    authorization: AuditEvidence,
    db_session: DatabaseSession,
) -> RetentionCleanupResponse:
    return await PrivacyRetentionService(db_session).run_retention_cleanup(
        actor_id=actor.user_id,
        permission=authorization.permission,
    )


@router.post(
    "/anonymize/{user_id}", response_model=AnonymizeUserResponse, deprecated=True
)
@user_policy("admin.privacy.manage", "all", "admin")
async def anonymize_user_account(
    user_id: UUID,
    payload: AnonymizeUserRequest,
    actor: CurrentActorDependency,
    authorization: AuditEvidence,
    db_session: DatabaseSession,
) -> AnonymizeUserResponse:
    return await PrivacyRetentionService(db_session).anonymize_user(
        user_id=user_id,
        actor_id=actor.user_id,
        reason=payload.reason,
        confirm_phrase=payload.confirm_phrase,
        actor_roles=actor.roles,
        authorization=authorization,
    )


@router.get("/holds/{user_id}", response_model=LegalHoldResponse)
@user_policy("admin.privacy.view", "all", "admin")
async def get_account_legal_hold(
    user_id: UUID,
    db_session: DatabaseSession,
) -> LegalHoldResponse:
    user = await db_session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "TÃ i khoáº£n khÃ´ng tá»“n táº¡i")

    is_held, reason = await PrivacyRetentionService(db_session).check_legal_hold(
        user_id
    )
    return LegalHoldResponse(
        user_id=user_id,
        legal_hold=is_held,
        reason=reason,
        updated_at=datetime.now(UTC),
    )


@router.post("/holds/{user_id}", response_model=LegalHoldResponse)
@user_policy("admin.privacy.manage", "all", "admin")
async def update_account_legal_hold(
    user_id: UUID,
    payload: LegalHoldRequest,
    actor: CurrentActorDependency,
    authorization: AuditEvidence,
    db_session: DatabaseSession,
) -> LegalHoldResponse:
    return await PrivacyRetentionService(db_session).set_legal_hold(
        user_id=user_id,
        hold=payload.hold,
        reason=payload.reason,
        actor_id=actor.user_id,
        authorization=authorization,
    )


@driver_router.post(
    "/anonymize-request", response_model=PrivacyReceipt, status_code=202
)
@user_policy("driver.privacy.request", "own", "driver")
async def driver_self_anonymize(
    payload: DriverPrivacyRequest,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> PrivacyReceipt:
    return await PrivacyRetentionService(db_session).create_request(
        user_id=actor.user_id,
        password=payload.current_password.get_secret_value(),
        reason=payload.reason or "Yêu cầu xử lý dữ liệu cá nhân",
    )


@driver_router.get("/requests", response_model=list[PrivacyReceipt])
@user_policy("driver.privacy.request", "own", "driver")
async def driver_privacy_requests(
    actor: CurrentActorDependency, db_session: DatabaseSession
) -> list[PrivacyReceipt]:
    return await PrivacyRetentionService(db_session).list_requests(actor.user_id)


@router.get("/requests", response_model=list[PrivacyReceipt])
@user_policy("admin.privacy.view", "all", "admin")
async def admin_privacy_requests(db_session: DatabaseSession) -> list[PrivacyReceipt]:
    return await PrivacyRetentionService(db_session).list_requests()


@router.post("/requests/{request_id}/decision", response_model=PrivacyReceipt)
@user_policy("admin.privacy.manage", "all", "admin")
async def review_privacy_request(
    request_id: UUID,
    payload: PrivacyDecision,
    actor: CurrentActorDependency,
    authorization: AuditEvidence,
    db_session: DatabaseSession,
) -> PrivacyReceipt:
    return await PrivacyRetentionService(db_session).review_request(
        request_id, payload, actor.user_id, authorization
    )
