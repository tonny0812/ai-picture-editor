"""提示词收藏与模板的业务逻辑。

两条贯穿始终的规则：
- **资源隔离**：所有查询都带 user_id。别人的收藏与自建模板一律当作不存在（404），
  不返回 403——避免泄露"这条数据存在但你没权限"的信息。
- **内置只读**：PromptTemplate.user_id 为 NULL 是内置模板，任何写操作都拒绝。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt import PromptEntry, PromptTemplate
from app.prompts import MissingVariable, render_template
from app.services import assets as asset_service
from app.services import runs as run_service
from app.services.runs import RunNotFound


class EntryNotFound(Exception):
    pass


class TemplateNotFound(Exception):
    pass


class BuiltinReadOnly(Exception):
    """试图修改或删除内置模板。"""


class AssetNotOwned(Exception):
    pass


class RunNotOwned(Exception):
    pass


MAX_LIMIT = 100


def _visible_templates(user_id: uuid.UUID) -> Select[tuple[PromptTemplate]]:
    """内置模板 + 自己的模板。"""
    return select(PromptTemplate).where(
        or_(PromptTemplate.user_id.is_(None), PromptTemplate.user_id == user_id)
    )


async def _require_asset(session: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID) -> None:
    if await asset_service.get_for_user(session, user_id, asset_id) is None:
        raise AssetNotOwned


async def _require_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> None:
    try:
        await run_service.get(session, run_id, user_id)
    except RunNotFound:
        raise RunNotOwned from None


# ------------------------------------------------------------------ 收藏

async def list_entries(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    category: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    limit: int = 50,
) -> list[PromptEntry]:
    query = select(PromptEntry).where(PromptEntry.user_id == user_id)
    if category:
        query = query.where(PromptEntry.category == category)
    if tag:
        query = query.where(PromptEntry.tags.contains([tag]))
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                PromptEntry.title.ilike(pattern),
                PromptEntry.prompt.ilike(pattern),
                PromptEntry.note.ilike(pattern),
            )
        )
    rows = await session.execute(
        query.order_by(PromptEntry.created_at.desc()).limit(min(limit, MAX_LIMIT))
    )
    return list(rows.scalars())


async def get_entry(
    session: AsyncSession, entry_id: uuid.UUID, user_id: uuid.UUID
) -> PromptEntry:
    row = await session.execute(
        select(PromptEntry).where(PromptEntry.id == entry_id, PromptEntry.user_id == user_id)
    )
    entry = row.scalar_one_or_none()
    if entry is None:
        raise EntryNotFound
    return entry


async def create_entry(
    session: AsyncSession, user_id: uuid.UUID, data: dict
) -> PromptEntry:
    if data.get("preview_asset_id"):
        await _require_asset(session, user_id, data["preview_asset_id"])
    if data.get("source_run_id"):
        await _require_run(session, user_id, data["source_run_id"])

    entry = PromptEntry(user_id=user_id, **data)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def update_entry(
    session: AsyncSession, entry_id: uuid.UUID, user_id: uuid.UUID, updates: dict
) -> PromptEntry:
    entry = await get_entry(session, entry_id, user_id)
    if updates.get("preview_asset_id"):
        await _require_asset(session, user_id, updates["preview_asset_id"])
    for key, value in updates.items():
        setattr(entry, key, value)
    await session.commit()
    await session.refresh(entry)
    return entry


async def delete_entry(session: AsyncSession, entry_id: uuid.UUID, user_id: uuid.UUID) -> None:
    entry = await get_entry(session, entry_id, user_id)
    await session.delete(entry)
    await session.commit()


async def mark_used(
    session: AsyncSession, entry_id: uuid.UUID, user_id: uuid.UUID
) -> PromptEntry:
    """复用一次：计数 + 记录时间，便于按常用排序。"""
    entry = await get_entry(session, entry_id, user_id)
    entry.use_count += 1
    entry.last_used_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(entry)
    return entry


# ------------------------------------------------------------------ 模板

async def list_templates(
    session: AsyncSession, user_id: uuid.UUID, *, category: str | None = None
) -> list[PromptTemplate]:
    """内置在前、自建在后；同组内按创建时间。"""
    query = _visible_templates(user_id)
    if category:
        query = query.where(PromptTemplate.category == category)
    rows = await session.execute(
        query.order_by(PromptTemplate.user_id.nullsfirst(), PromptTemplate.created_at)
    )
    return list(rows.scalars())


async def get_template(
    session: AsyncSession, template_id: uuid.UUID, user_id: uuid.UUID
) -> PromptTemplate:
    row = await session.execute(
        _visible_templates(user_id).where(PromptTemplate.id == template_id)
    )
    template = row.scalar_one_or_none()
    if template is None:
        raise TemplateNotFound
    return template


async def create_template(
    session: AsyncSession, user_id: uuid.UUID, data: dict
) -> PromptTemplate:
    if data.get("preview_asset_id"):
        await _require_asset(session, user_id, data["preview_asset_id"])
    template = PromptTemplate(user_id=user_id, **data)
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template


async def update_template(
    session: AsyncSession, template_id: uuid.UUID, user_id: uuid.UUID, updates: dict
) -> PromptTemplate:
    template = await get_template(session, template_id, user_id)
    if template.is_builtin:
        raise BuiltinReadOnly
    if updates.get("preview_asset_id"):
        await _require_asset(session, user_id, updates["preview_asset_id"])
    for key, value in updates.items():
        setattr(template, key, value)
    await session.commit()
    await session.refresh(template)
    return template


async def delete_template(
    session: AsyncSession, template_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    template = await get_template(session, template_id, user_id)
    if template.is_builtin:
        raise BuiltinReadOnly
    await session.delete(template)
    await session.commit()


async def render(
    session: AsyncSession, template_id: uuid.UUID, user_id: uuid.UUID, values: dict[str, str]
) -> tuple[str, str | None]:
    """渲染模板，返回 (prompt, negative_prompt)。缺必填变量时抛 MissingVariable。"""
    template = await get_template(session, template_id, user_id)
    prompt = render_template(template.prompt_template, values)
    negative = None
    if template.negative_template:
        # 负面词模板里的缺失变量按空处理即可，不打断用户
        try:
            negative = render_template(template.negative_template, values) or None
        except MissingVariable:
            negative = None
    template.use_count += 1
    await session.commit()
    return prompt, negative
