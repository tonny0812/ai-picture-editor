"""提示词收藏与模板。

分两张表而不是一张：收藏是「成品」（具体的一段话，可直接用），模板是「骨架」
（带变量，需要填）。混在一张表里会让半数字段永远为空。

内置模板的 user_id 为 NULL：所有人可见、可读，但写操作一律拒绝，
避免公共内容被误改。
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TIMESTAMPTZ, UUIDBase

# 内置种子使用的分类；category 不加约束，用户可以自填新分类
PORTRAIT = "portrait"
KNOWLEDGE_GRAPH = "knowledge_graph"
ARCHITECTURE = "architecture"
PRODUCT = "product"
POSTER = "poster"
ILLUSTRATION = "illustration"
OTHER = "other"


class PromptEntry(UUIDBase):
    """一条收进库的成品提示词，带预览图与溯源。"""

    __tablename__ = "prompt_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(80))
    prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text, default=None)
    ratio: Mapped[str] = mapped_column(String(8), default="1:1")
    category: Mapped[str] = mapped_column(String(32), default=OTHER, index=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    # 预览图复用已有素材（on delete SET NULL）：素材删了收藏还在，只是没图
    preview_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), default=None
    )
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tool_runs.id", ondelete="SET NULL"), default=None
    )
    use_count: Mapped[int] = mapped_column(default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now(), onupdate=func.now()
    )


class PromptTemplate(UUIDBase):
    """带变量的提示词骨架。user_id 为 NULL 表示内置模板。"""

    __tablename__ = "prompt_templates"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), default=None, index=True
    )
    title: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(32), default=OTHER, index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    prompt_template: Mapped[str] = mapped_column(Text)
    negative_template: Mapped[str | None] = mapped_column(Text, default=None)
    # [{"name","label","placeholder","default","options":[]}]，顺序即表单顺序
    variables: Mapped[list] = mapped_column(JSONB, default=list)
    default_ratio: Mapped[str] = mapped_column(String(8), default="1:1")
    default_count: Mapped[int] = mapped_column(default=4)
    preview_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), default=None
    )
    use_count: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now(), onupdate=func.now()
    )

    @property
    def is_builtin(self) -> bool:
        return self.user_id is None
