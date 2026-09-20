"""LLM 接口配置：单表两域（scope=global 全局默认 / scope=user 个人覆盖）。

NULL = 不覆盖该字段，回落到下一层（用户 → 全局 → .env），
因此用户覆盖只需填写自己想改的字段。密钥列只存 Fernet 密文。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TIMESTAMPTZ, UUIDBase


class LlmConfig(UUIDBase):
    __tablename__ = "llm_configs"
    __table_args__ = (
        Index(
            "uq_llm_config_global",
            "scope",
            unique=True,
            postgresql_where=text("scope = 'global'"),
        ),
        Index(
            "uq_llm_config_user",
            "user_id",
            unique=True,
            postgresql_where=text("scope = 'user'"),
        ),
    )

    scope: Mapped[str] = mapped_column(String(8))  # global | user
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # ---- 对话规划（OpenAI 兼容）----
    planner_base_url: Mapped[str | None] = mapped_column(String(512))
    planner_api_key_enc: Mapped[str | None] = mapped_column(String(1024))
    planner_model: Mapped[str | None] = mapped_column(String(128))
    planner_timeout: Mapped[int | None] = mapped_column(Integer)
    planner_max_retries: Mapped[int | None] = mapped_column(Integer)

    # ---- 图像模型（OpenAI 兼容 images API）----
    images_base_url: Mapped[str | None] = mapped_column(String(512))
    images_api_key_enc: Mapped[str | None] = mapped_column(String(1024))
    images_model: Mapped[str | None] = mapped_column(String(128))
    images_sizes: Mapped[str | None] = mapped_column(String(256))

    # ---- provider 总开关 ----
    image_provider: Mapped[str | None] = mapped_column(String(16))
    # 仅全局行有意义：开启后禁止用户覆盖 image_provider
    lock_image_provider: Mapped[bool] = mapped_column(Boolean, default=False)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now(), onupdate=func.now()
    )


class LlmConfigAudit(UUIDBase):
    """配置变更审计。diff 只记字段名与非密钥值，密钥一律记「已变更/已清除」。"""

    __tablename__ = "llm_config_audit"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    scope: Mapped[str] = mapped_column(String(8))
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(16))  # update | clear | test
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
