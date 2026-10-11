"""One assignment entry point for API and seed tools; caller owns transaction."""

from collections.abc import Collection
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.driver_provisioning import ensure_driver_resources
from src.modules.identity.models import Role, User, UserRole

KNOWN_ROLES = frozenset({"admin", "operator", "accountant", "station_owner", "driver"})
# No prohibited combination has been approved yet.
FORBIDDEN_ROLE_PAIRS: frozenset[frozenset[str]] = frozenset()


def validate_role_assignment(
    roles: Collection[str], *, forbidden_pairs: Collection[frozenset[str]] | None = None
) -> None:
    final = frozenset(roles)
    if not final or len(final) != len(roles) or not final <= KNOWN_ROLES:
        raise HTTPException(422, "Danh sách vai trò không hợp lệ")
    pairs = FORBIDDEN_ROLE_PAIRS if forbidden_pairs is None else forbidden_pairs
    if any(pair <= final for pair in pairs):
        raise HTTPException(422, "Tổ hợp vai trò không được phép")


async def assign_user_roles(
    db: AsyncSession, user_id: UUID, roles: Collection[str], *, replace: bool = True
) -> None:
    # Serialize additions/replacements on the same user, including seed operations.
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(404, "Tài khoản không tồn tại")
    validate_role_assignment(roles, forbidden_pairs=())
    final = set(roles)
    if not replace:
        final.update(
            await db.scalars(
                select(Role.code).join(UserRole).where(UserRole.user_id == user_id)
            )
        )
    validate_role_assignment(list(final))
    previous = list(
        (
            await db.execute(
                select(Role.code, UserRole.is_default)
                .join(UserRole)
                .where(UserRole.user_id == user_id)
            )
        ).all()
    )
    default = next((code for code, flag in previous if flag), None)
    if not previous and len(final) == 1:
        default = next(iter(final))
    assignments = list(
        (await db.execute(select(Role.id, Role.code).where(Role.code.in_(final)))).all()
    )
    if len(assignments) != len(final):
        raise HTTPException(409, "Danh mục vai trò chưa được khởi tạo đầy đủ")
    await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    db.add_all(
        [
            UserRole(user_id=user_id, role_id=role_id, is_default=code == default)
            for role_id, code in assignments
        ]
    )
    await db.flush()

    if "driver" in final:
        await ensure_driver_resources(db, user)


async def get_default_role(db: AsyncSession, user_id: UUID) -> str | None:
    return cast(
        str | None,
        await db.scalar(
            select(Role.code)
            .join(UserRole)
            .where(UserRole.user_id == user_id, UserRole.is_default.is_(True))
        ),
    )


async def set_default_role(db: AsyncSession, user_id: UUID, code: str | None) -> None:
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(404, "Tài khoản không tồn tại")
    role_id = None
    if code is not None:
        role_id = await db.scalar(
            select(Role.id)
            .join(UserRole)
            .where(UserRole.user_id == user_id, Role.code == code)
        )
        if role_id is None:
            raise HTTPException(422, "Vai trò mặc định phải thuộc vai trò đã được cấp")
    await db.execute(
        update(UserRole).where(UserRole.user_id == user_id).values(is_default=False)
    )
    if role_id is not None:
        await db.execute(
            update(UserRole)
            .where(UserRole.user_id == user_id, UserRole.role_id == role_id)
            .values(is_default=True)
        )
    user.updated_at = datetime.now(UTC)
    await db.flush()
