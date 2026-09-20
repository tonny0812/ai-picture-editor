import enum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UUIDBase, enum_column


class Role(enum.StrEnum):
    """账号角色。admin 才可查看/修改全局 LLM 配置与调整他人角色。"""

    USER = "user"
    ADMIN = "admin"

    @property
    def is_admin(self) -> bool:
        return self is Role.ADMIN


class User(UUIDBase):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[Role] = mapped_column(enum_column(Role), default=Role.USER)
