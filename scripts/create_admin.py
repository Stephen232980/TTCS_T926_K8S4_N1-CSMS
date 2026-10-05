import asyncio

from sqlalchemy import select

from src.modules.identity.models import Role, User, UserRole
from src.modules.identity.security import hash_password
from src.platform.database.session import SessionFactory


async def main():
    async with SessionFactory() as session:
        # Check if admin role exists
        result = await session.execute(select(Role).where(Role.code == "admin"))
        admin_role = result.scalar_one_or_none()
        if not admin_role:
            admin_role = Role(code="admin")
            session.add(admin_role)
            await session.commit()
            await session.refresh(admin_role)
            
        # Check if user exists
        email = "Admin@gmail.com".lower()
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                email=email,
                password_hash=hash_password("admin123"),
                status="active"
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            
        # Assign role
        result = await session.execute(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == admin_role.id)
        )
        user_role = result.scalar_one_or_none()
        if not user_role:
            user_role = UserRole(user_id=user.id, role_id=admin_role.id)
            session.add(user_role)
            await session.commit()
            
        print("Admin user created successfully.")

import selectors

if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
