import asyncio
import selectors

from sqlalchemy import select

from src.modules.identity.models import Role, User
from src.modules.identity.role_assignment import assign_user_roles
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
            async with session.begin():
                role_obj = await session.scalar(
                    select(Role).where(Role.code == acc["role"])
                )
                if role_obj is None:
                    session.add(Role(code=acc["role"]))
                    await session.flush()
                user = await session.scalar(
                    select(User).where(User.email == acc["email"].lower())
                )
                if user is None:
                    user = User(
                        email=acc["email"],
                        password_hash=hash_password(acc["password"]),
                        status="active",
                    )
                    session.add(user)
                    await session.flush()
                await assign_user_roles(session, user.id, [acc["role"]], replace=False)
            print(f"Ready: {acc['email']} ({acc['role']})")


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
