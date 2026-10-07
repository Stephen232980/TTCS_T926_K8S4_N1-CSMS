import asyncio
import selectors

from sqlalchemy import select

from src.modules.identity.models import Role, User, UserRole
from src.modules.identity.security import hash_password
from src.platform.database.session import SessionFactory

accounts = [
    {
        "email": "admin-ui-test@example.com",
        "password": "Admin-UI-local-2026!",
        "role": "admin",
    },
    {
        "email": "demo.owner.20261005@example.com",
        "password": "Demo-Owner-2026!",
        "role": "station_owner",
    },
    {
        "email": "demo.owner2.20261005@example.com",
        "password": "Demo-Owner2-2026!",
        "role": "station_owner",
    },
    {
        "email": "demo.operator.20261005@example.com",
        "password": "Demo-Ops-2026!",
        "role": "operator",
    },
    {
        "email": "demo.driver.20261005@example.com",
        "password": "Demo-Driver-2026!",
        "role": "driver",
    },
    {
        "email": "demo.accountant.20261005@example.com",
        "password": "Demo-Acct-2026!",
        "role": "accountant",
    },
]


async def main():
    async with SessionFactory() as session:
        for acc in accounts:
            # Check/Create role
            result = await session.execute(select(Role).where(Role.code == acc["role"]))
            role_obj = result.scalar_one_or_none()
            if not role_obj:
                role_obj = Role(code=acc["role"])
                session.add(role_obj)
                await session.commit()
                await session.refresh(role_obj)

            # Check/Create user
            email = acc["email"].lower()
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if not user:
                user = User(
                    email=email,
                    password_hash=hash_password(acc["password"]),
                    status="active",
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)

            # Assign role
            result = await session.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id, UserRole.role_id == role_obj.id
                )
            )
            user_role = result.scalar_one_or_none()
            if not user_role:
                user_role = UserRole(
                    user_id=user.id, role_id=role_obj.id, is_default=True
                )
                session.add(user_role)
                await session.commit()
                print(f"Created {acc['email']} with role {acc['role']}")
            else:
                print(f"User {acc['email']} already exists and has role {acc['role']}")


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
