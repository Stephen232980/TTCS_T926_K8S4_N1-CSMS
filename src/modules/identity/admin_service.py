import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.admin_schemas import (
    AccountCreateRequest,
    AccountListQuery,
    AccountListResponse,
    AccountResponse,
    AccountStatus,
    AccountUpdateRequest,
    RoleCode,
    RoleResponse,
)
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.models import AccountAudit, Role, Session, User, UserRole
from src.modules.identity.security import hash_password

ROLE_NAMES: dict[RoleCode, str] = {
    "admin": "Quản trị",
    "operator": "Vận hành",
    "station_owner": "Chủ trạm",
    "driver": "Tài xế",
    "accountant": "Kế toán",
}


class AdminAccountService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def roles(self) -> list[RoleResponse]:
        codes = await self.db.scalars(select(Role.code).order_by(Role.code))
        return [
            RoleResponse(code=c, name=ROLE_NAMES[c]) for c in codes if c in ROLE_NAMES
        ]

    async def account(self, user: User) -> AccountResponse:
        codes = await self.db.scalars(
            select(Role.code)
            .join(UserRole)
            .where(UserRole.user_id == user.id)
            .order_by(Role.code)
        )
        return AccountResponse(
            id=user.id,
            email=user.email,
            roles=[cast(RoleCode, c) for c in codes],
            status=cast(AccountStatus, user.status),
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    async def detail(self, user_id: UUID) -> AccountResponse:
        user = await self.db.get(User, user_id)
        if user is None:
            raise HTTPException(404, "Tài khoản không tồn tại")
        return await self.account(user)

    async def list_accounts(self, query: AccountListQuery) -> AccountListResponse:
        statement = select(User)
        if query.search and query.search.strip():
            statement = statement.where(
                User.email.contains(query.search.strip().lower(), autoescape=True)
            )
        if query.status:
            statement = statement.where(User.status == query.status)
        if query.role:
            statement = statement.where(
                User.id.in_(
                    select(UserRole.user_id).join(Role).where(Role.code == query.role)
                )
            )
        total = await self.db.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        users = await self.db.scalars(
            statement.order_by(User.created_at.desc(), User.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        # One role query for the whole page; no per-row fetches.
        items = list(users)
        assignments = await self.db.execute(
            select(UserRole.user_id, Role.code)
            .join(Role)
            .where(UserRole.user_id.in_([u.id for u in items]))
            .order_by(Role.code)
        )
        roles: dict[UUID, list[RoleCode]] = {}
        for uid, code in assignments:
            roles.setdefault(uid, []).append(cast(RoleCode, code))
        return AccountListResponse(
            items=[
                AccountResponse(
                    id=u.id,
                    email=u.email,
                    roles=roles.get(u.id, []),
                    status=cast(AccountStatus, u.status),
                    created_at=u.created_at,
                    updated_at=u.updated_at,
                )
                for u in items
            ],
            page=query.page,
            page_size=query.page_size,
            total=total or 0,
            total_pages=((total or 0) + query.page_size - 1) // query.page_size,
        )

    async def _lock_admin(self, actor: CurrentActor) -> User:
        # Serialize admin mutations, including simultaneous removal of different admins.
        # Hashing is performed before taking this short transaction lock.
        await self.db.execute(text("SELECT pg_advisory_xact_lock(610003)"))
        user = await self.db.scalar(
            select(User)
            .where(User.id == actor.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        code = await self.db.scalar(
            select(Role.code)
            .join(UserRole)
            .where(UserRole.user_id == actor.user_id, Role.code == "admin")
        )
        if user is None or user.status != "active" or code is None:
            raise HTTPException(403, "Không còn quyền quản trị tài khoản")
        return user

    async def _role_ids(self, codes: list[RoleCode]) -> list[UUID]:
        ids = list(await self.db.scalars(select(Role.id).where(Role.code.in_(codes))))
        if len(ids) != len(codes):
            raise HTTPException(409, "Danh mục vai trò chưa được khởi tạo đầy đủ")
        return ids

    def _audit(
        self,
        actor: User,
        target: User,
        action: str,
        before: AccountResponse | None,
        after: AccountResponse,
    ) -> None:
        def state(account: AccountResponse) -> dict[str, object]:
            return {
                "email": account.email,
                "roles": account.roles,
                "status": account.status,
            }

        self.db.add(
            AccountAudit(
                actor_id=actor.id,
                target_id=target.id,
                action=action,
                before_state=state(before) if before else None,
                after_state=state(after),
                created_at=datetime.now(UTC),
            )
        )

    async def create(
        self, payload: AccountCreateRequest, actor: CurrentActor
    ) -> AccountResponse:
        password_hash = await asyncio.to_thread(
            hash_password, payload.password.get_secret_value()
        )
        try:
            admin = await self._lock_admin(actor)
            ids = await self._role_ids(payload.roles)
            user = User(email=str(payload.email), password_hash=password_hash)
            self.db.add(user)
            await self.db.flush()
            self.db.add_all([UserRole(user_id=user.id, role_id=r) for r in ids])
            await self.db.flush()
            result = await self.account(user)
            self._audit(admin, user, "account_created", None, result)
            await self.db.commit()
            return result
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                409, "Email đã được sử dụng hoặc dữ liệu xung đột"
            ) from exc
        except Exception:
            await self.db.rollback()
            raise

    async def change(
        self, user_id: UUID, payload: AccountUpdateRequest, actor: CurrentActor
    ) -> AccountResponse:
        try:
            admin = await self._lock_admin(actor)
            user = await self.db.scalar(
                select(User)
                .where(User.id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if user is None:
                raise HTTPException(404, "Tài khoản không tồn tại")
            before = await self.account(user)
            if before.updated_at != payload.expected_updated_at:
                raise HTTPException(
                    409, "Tài khoản đã thay đổi. Hãy tải lại trước khi sửa"
                )
            if user.status not in {"active", "suspended"}:
                raise HTTPException(409, "Không thể sửa tài khoản đã ngừng hoạt động")
            new_roles = payload.roles if payload.roles is not None else before.roles
            new_status = payload.status or before.status
            loses_admin = "admin" in before.roles and (
                "admin" not in new_roles or new_status != "active"
            )
            if user_id == actor.user_id and (
                new_status != "active" or "admin" not in new_roles
            ):
                raise HTTPException(409, "Không thể tự khóa hoặc tự bỏ quyền quản trị")
            if loses_admin and before.status == "active":
                other = await self.db.scalar(
                    select(User.id)
                    .join(UserRole)
                    .join(Role)
                    .where(
                        User.status == "active",
                        Role.code == "admin",
                        User.id != user_id,
                    )
                    .limit(1)
                )
                if other is None:
                    raise HTTPException(
                        409, "Phải giữ ít nhất một quản trị viên hoạt động"
                    )
            if new_roles == before.roles and new_status == before.status:
                await self.db.rollback()
                return before
            if payload.roles is not None:
                ids = await self._role_ids(payload.roles)
                await self.db.execute(
                    delete(UserRole).where(UserRole.user_id == user_id)
                )
                self.db.add_all([UserRole(user_id=user_id, role_id=r) for r in ids])
            user.status = new_status
            user.updated_at = datetime.now(UTC)
            if new_status == "suspended":
                await self.db.execute(
                    update(Session)
                    .where(Session.user_id == user_id, Session.revoked_at.is_(None))
                    .values(revoked_at=datetime.now(UTC))
                )
            await self.db.flush()
            result = await self.account(user)
            self._audit(admin, user, "account_updated", before, result)
            await self.db.commit()
            return result
        except Exception:
            await self.db.rollback()
            raise
