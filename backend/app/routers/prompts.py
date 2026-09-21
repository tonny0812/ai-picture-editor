"""提示词收藏与模板。

- /api/prompts/entries   自己的收藏（增删改查 + 复用计数）
- /api/prompts/templates 内置模板（只读）+ 自建模板（增删改查）+ 渲染
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.db import SessionDep
from app.deps import CurrentUser
from app.prompts import MissingVariable
from app.schemas.prompt import (
    EntryIn,
    EntryOut,
    EntryPatch,
    RenderIn,
    RenderOut,
    TemplateIn,
    TemplateOut,
    TemplatePatch,
)
from app.services import prompts as service

router = APIRouter(prefix="/prompts", tags=["prompts"])

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "这条提示词不存在")
_TEMPLATE_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "这个模板不存在")
_BUILTIN = HTTPException(status.HTTP_403_FORBIDDEN, "内置模板不可修改，可以复制一份再改")
_BAD_ASSET = HTTPException(status.HTTP_404_NOT_FOUND, "预览图不存在")
_BAD_RUN = HTTPException(status.HTTP_404_NOT_FOUND, "来源任务不存在")


# ------------------------------------------------------------------ 收藏

@router.get("/entries", response_model=list[EntryOut])
async def list_entries(
    user: CurrentUser,
    session: SessionDep,
    category: str | None = Query(default=None, max_length=32),
    tag: str | None = Query(default=None, max_length=16),
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[EntryOut]:
    entries = await service.list_entries(
        session, user.id, category=category, tag=tag, q=q, limit=limit
    )
    return [EntryOut.of(entry) for entry in entries]


@router.post("/entries", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(payload: EntryIn, user: CurrentUser, session: SessionDep) -> EntryOut:
    try:
        entry = await service.create_entry(session, user.id, payload.cleaned())
    except service.AssetNotOwned:
        raise _BAD_ASSET from None
    except service.RunNotOwned:
        raise _BAD_RUN from None
    return EntryOut.of(entry)


@router.get("/entries/{entry_id}", response_model=EntryOut)
async def get_entry(entry_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> EntryOut:
    try:
        entry = await service.get_entry(session, entry_id, user.id)
    except service.EntryNotFound:
        raise _NOT_FOUND from None
    return EntryOut.of(entry)


@router.patch("/entries/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: uuid.UUID, payload: EntryPatch, user: CurrentUser, session: SessionDep
) -> EntryOut:
    try:
        entry = await service.update_entry(session, entry_id, user.id, payload.updates())
    except service.EntryNotFound:
        raise _NOT_FOUND from None
    except service.AssetNotOwned:
        raise _BAD_ASSET from None
    return EntryOut.of(entry)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    try:
        await service.delete_entry(session, entry_id, user.id)
    except service.EntryNotFound:
        raise _NOT_FOUND from None


@router.post("/entries/{entry_id}/use", response_model=EntryOut)
async def use_entry(entry_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> EntryOut:
    """复用一次：累计使用次数，前端列表可据此排「常用」。"""
    try:
        entry = await service.mark_used(session, entry_id, user.id)
    except service.EntryNotFound:
        raise _NOT_FOUND from None
    return EntryOut.of(entry)


# ------------------------------------------------------------------ 模板

@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(
    user: CurrentUser,
    session: SessionDep,
    category: str | None = Query(default=None, max_length=32),
) -> list[TemplateOut]:
    templates = await service.list_templates(session, user.id, category=category)
    return [TemplateOut.of(item) for item in templates]


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateIn, user: CurrentUser, session: SessionDep
) -> TemplateOut:
    try:
        template = await service.create_template(session, user.id, payload.cleaned())
    except service.AssetNotOwned:
        raise _BAD_ASSET from None
    return TemplateOut.of(template)


@router.get("/templates/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TemplateOut:
    try:
        template = await service.get_template(session, template_id, user.id)
    except service.TemplateNotFound:
        raise _TEMPLATE_NOT_FOUND from None
    return TemplateOut.of(template)


@router.patch("/templates/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: uuid.UUID, payload: TemplatePatch, user: CurrentUser, session: SessionDep
) -> TemplateOut:
    try:
        template = await service.update_template(session, template_id, user.id, payload.updates())
    except service.TemplateNotFound:
        raise _TEMPLATE_NOT_FOUND from None
    except service.BuiltinReadOnly:
        raise _BUILTIN from None
    except service.AssetNotOwned:
        raise _BAD_ASSET from None
    return TemplateOut.of(template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    try:
        await service.delete_template(session, template_id, user.id)
    except service.TemplateNotFound:
        raise _TEMPLATE_NOT_FOUND from None
    except service.BuiltinReadOnly:
        raise _BUILTIN from None


@router.post("/templates/{template_id}/render", response_model=RenderOut)
async def render_template(
    template_id: uuid.UUID, payload: RenderIn, user: CurrentUser, session: SessionDep
) -> RenderOut:
    """填变量出成品提示词。缺必填变量时把缺哪个说清楚。"""
    try:
        prompt, negative = await service.render(session, template_id, user.id, payload.values)
    except service.TemplateNotFound:
        raise _TEMPLATE_NOT_FOUND from None
    except MissingVariable as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return RenderOut(prompt=prompt, negative_prompt=negative)
