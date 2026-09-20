import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Role, User
from app.security import hash_password, verify_password


class UsernameTaken(Exception):
    pass


class InvalidCredentials(Exception):
    pass


async def register(session: AsyncSession, username: str, password: str) -> User:
    role = Role.ADMIN if username in get_settings().admin_username_set else Role.USER
    user = User(username=username, password_hash=hash_password(password), role=role)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise UsernameTaken from exc
    return user


async def authenticate(session: AsyncSession, username: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentials
    return user


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_by_username(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(select(User).where(User.username == username))


async def list_users(session: AsyncSession, limit: int = 200) -> list[User]:
    result = await session.scalars(
        select(User).order_by(User.created_at, User.id).limit(limit)
    )
    return list(result)


async def set_role(session: AsyncSession, user: User, role: Role) -> User:
    user.role = role
    await session.commit()
    return user


async def count_admins(session: AsyncSession) -> int:
    """用于防止把最后一个管理员降级后系统失去管理入口。"""
    admins = await session.scalars(select(User.id).where(User.role == Role.ADMIN))
    return len(list(admins))
