from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.admin_router import AdminAccountRoute
from src.modules.identity.admin_schemas import AccountStatus, RoleCode
from src.modules.identity.authorization import allow_roles
from src.modules.identity.dependencies import authorize_request
from src.modules.identity.models import AccountAudit, User
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/account-audit",
    tags=["admin-audit"],
    dependencies=[Depends(authorize_request)],
    route_class=AdminAccountRoute,
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


class AccountAuditQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    actor_email: str | None = Field(default=None, min_length=1, max_length=320)
    target_id: UUID | None = None
    action: Literal["account_created", "account_updated"] | None = None
    from_at: AwareDatetime | None = None
    to_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_window(self) -> Self:
        if self.from_at and self.to_at and self.from_at > self.to_at:
            raise ValueError("Thời gian bắt đầu phải trước thời gian kết thúc")
        return self


class AccountAuditState(BaseModel):
    email: str
    roles: list[RoleCode]
    status: AccountStatus


class AccountAuditEntry(BaseModel):
    id: UUID
    actor_id: UUID
    actor_email: str
    target_id: UUID
    action: str
    before: AccountAuditState | None
    after: AccountAuditState
    created_at: datetime


class AccountAuditPage(BaseModel):
    items: list[AccountAuditEntry]
    page: int
    page_size: int
    total: int
    total_pages: int


@router.get("", response_model=AccountAuditPage)
@allow_roles("admin")
async def account_audit(
    db: Database,
    query: Annotated[AccountAuditQuery, Query()],
) -> AccountAuditPage:
    statement = select(AccountAudit, User.email).join(
        User, User.id == AccountAudit.actor_id
    )
    if query.actor_email:
        statement = statement.where(User.email == query.actor_email.strip().lower())
    if query.target_id:
        statement = statement.where(AccountAudit.target_id == query.target_id)
    if query.action:
        statement = statement.where(AccountAudit.action == query.action)
    if query.from_at:
        statement = statement.where(AccountAudit.created_at >= query.from_at)
    if query.to_at:
        statement = statement.where(AccountAudit.created_at <= query.to_at)
    total = await db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = await db.execute(
        statement.order_by(AccountAudit.created_at.desc(), AccountAudit.id)
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    )
    return AccountAuditPage(
        items=[
            AccountAuditEntry(
                id=row.id,
                actor_id=row.actor_id,
                actor_email=email,
                target_id=row.target_id,
                action=row.action,
                before=AccountAuditState.model_validate(row.before_state)
                if row.before_state
                else None,
                after=AccountAuditState.model_validate(row.after_state),
                created_at=row.created_at,
            )
            for row, email in rows
        ],
        page=query.page,
        page_size=query.page_size,
        total=total,
        total_pages=(total + query.page_size - 1) // query.page_size,
    )
