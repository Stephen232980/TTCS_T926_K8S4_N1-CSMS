"""One assignment entry point for API and seed tools; caller owns transaction."""

from collections.abc import Collection
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    ids = list(await db.scalars(select(Role.id).where(Role.code.in_(final))))
    if len(ids) != len(final):
        raise HTTPException(409, "Danh mục vai trò chưa được khởi tạo đầy đủ")
    await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    db.add_all([UserRole(user_id=user_id, role_id=role_id) for role_id in ids])
    await db.flush()
