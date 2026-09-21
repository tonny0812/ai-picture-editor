"""提示词收藏与模板的输入输出结构。"""

import uuid
from typing import Annotated

from pydantic import BaseModel, Field

from app.models.prompt import PromptEntry, PromptTemplate
from app.ratios import Ratio
from app.schemas.run import MAX_PROMPT

MAX_TITLE = 80
MAX_NOTE = 500
MAX_TAGS = 12
MAX_TAG = 16
MAX_CATEGORY = 32


def _clean_tags(tags: list[str]) -> list[str]:
    """去空白、去重、丢弃超长项。"""
    result: list[str] = []
    for tag in tags:
        value = tag.strip()
        if value and len(value) <= MAX_TAG and value not in result:
            result.append(value)
    return result[:MAX_TAGS]


class TemplateVariable(BaseModel):
    """表单里的一个空。options 非空时前端渲染为下拉，否则是输入框。"""

    name: Annotated[str, Field(max_length=32)]
    label: str = ""
    placeholder: str = ""
    default: str = ""
    options: list[str] = []


class EntryIn(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=MAX_TITLE)]
    prompt: Annotated[str, Field(min_length=1, max_length=MAX_PROMPT)]
    negative_prompt: Annotated[str | None, Field(max_length=MAX_PROMPT)] = None
    ratio: Ratio = Ratio.SQUARE
    category: Annotated[str, Field(max_length=MAX_CATEGORY)] = "other"
    tags: Annotated[list[str], Field(max_length=MAX_TAGS)] = []
    note: Annotated[str | None, Field(max_length=MAX_NOTE)] = None
    preview_asset_id: uuid.UUID | None = None
    source_run_id: uuid.UUID | None = None

    def cleaned_tags(self) -> list[str]:
        return _clean_tags(self.tags)

    def cleaned(self) -> dict:
        """去掉前后空白，空串归一为 None。"""
        data = self.model_dump(exclude={"tags"})
        data["tags"] = self.cleaned_tags()
        data["title"] = self.title.strip()
        data["prompt"] = self.prompt.strip()
        data["category"] = (self.category or "").strip() or "other"
        if data.get("negative_prompt"):
            data["negative_prompt"] = data["negative_prompt"].strip() or None
        if data.get("note"):
            data["note"] = data["note"].strip() or None
        else:
            data["note"] = None
        return data


class EntryPatch(BaseModel):
    title: Annotated[str | None, Field(max_length=MAX_TITLE)] = None
    prompt: Annotated[str | None, Field(max_length=MAX_PROMPT)] = None
    negative_prompt: Annotated[str | None, Field(max_length=MAX_PROMPT)] = None
    ratio: Ratio | None = None
    category: Annotated[str | None, Field(max_length=MAX_CATEGORY)] = None
    tags: Annotated[list[str] | None, Field(max_length=MAX_TAGS)] = None
    note: Annotated[str | None, Field(max_length=MAX_NOTE)] = None
    preview_asset_id: uuid.UUID | None = None

    def updates(self) -> dict:
        """只返回本次真正提交的字段，未提交的保持原值。"""
        provided = self.model_dump(exclude_unset=True)
        updates: dict = {}
        for key, value in provided.items():
            if key == "tags":
                if value is not None:
                    updates["tags"] = _clean_tags(value)
            elif isinstance(value, str):
                updates[key] = value.strip() or None
            else:
                updates[key] = value
        if "title" in updates and not updates["title"]:
            updates.pop("title")
        if "prompt" in updates and not updates["prompt"]:
            updates.pop("prompt")
        return updates


class EntryOut(BaseModel):
    id: uuid.UUID
    title: str
    prompt: str
    negative_prompt: str | None
    ratio: str
    category: str
    tags: list[str]
    note: str | None
    preview_asset_id: uuid.UUID | None
    source_run_id: uuid.UUID | None
    use_count: int
    last_used_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def of(cls, entry: PromptEntry) -> "EntryOut":
        return cls(
            id=entry.id,
            title=entry.title,
            prompt=entry.prompt,
            negative_prompt=entry.negative_prompt,
            ratio=entry.ratio,
            category=entry.category,
            tags=list(entry.tags or []),
            note=entry.note,
            preview_asset_id=entry.preview_asset_id,
            source_run_id=entry.source_run_id,
            use_count=entry.use_count,
            last_used_at=entry.last_used_at.isoformat() if entry.last_used_at else None,
            created_at=entry.created_at.isoformat(),
            updated_at=entry.updated_at.isoformat() if entry.updated_at else "",
        )


class TemplateIn(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=MAX_TITLE)]
    category: Annotated[str, Field(max_length=MAX_CATEGORY)] = "other"
    description: Annotated[str | None, Field(max_length=MAX_NOTE)] = None
    prompt_template: Annotated[str, Field(min_length=1, max_length=MAX_PROMPT)]
    negative_template: Annotated[str | None, Field(max_length=MAX_PROMPT)] = None
    variables: Annotated[list[TemplateVariable], Field(max_length=20)] = []
    default_ratio: Ratio = Ratio.SQUARE
    default_count: Annotated[int, Field(ge=1, le=6)] = 4
    preview_asset_id: uuid.UUID | None = None

    def cleaned(self) -> dict:
        data = self.model_dump()
        data["title"] = self.title.strip()
        data["category"] = (self.category or "").strip() or "other"
        data["prompt_template"] = self.prompt_template.strip()
        if data.get("negative_template"):
            data["negative_template"] = data["negative_template"].strip() or None
        if data.get("description"):
            data["description"] = data["description"].strip() or None
        return data


class TemplatePatch(BaseModel):
    title: Annotated[str | None, Field(max_length=MAX_TITLE)] = None
    category: Annotated[str | None, Field(max_length=MAX_CATEGORY)] = None
    description: Annotated[str | None, Field(max_length=MAX_NOTE)] = None
    prompt_template: Annotated[str | None, Field(max_length=MAX_PROMPT)] = None
    negative_template: Annotated[str | None, Field(max_length=MAX_PROMPT)] = None
    variables: Annotated[list[TemplateVariable] | None, Field(max_length=20)] = None
    default_ratio: Ratio | None = None
    default_count: Annotated[int | None, Field(ge=1, le=6)] = None
    preview_asset_id: uuid.UUID | None = None

    def updates(self) -> dict:
        updates: dict = {}
        for key, value in self.model_dump(exclude_unset=True).items():
            if key == "variables":
                if value is not None:
                    updates["variables"] = [item for item in value]
            elif isinstance(value, str):
                updates[key] = value.strip() or None
            else:
                updates[key] = value
        if "title" in updates and not updates["title"]:
            updates.pop("title")
        if "prompt_template" in updates and not updates["prompt_template"]:
            updates.pop("prompt_template")
        return updates


class TemplateOut(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    description: str | None
    prompt_template: str
    negative_template: str | None
    variables: list[dict]
    default_ratio: str
    default_count: int
    preview_asset_id: uuid.UUID | None
    use_count: int
    is_builtin: bool
    created_at: str

    @classmethod
    def of(cls, template: PromptTemplate) -> "TemplateOut":
        return cls(
            id=template.id,
            title=template.title,
            category=template.category,
            description=template.description,
            prompt_template=template.prompt_template,
            negative_template=template.negative_template,
            variables=list(template.variables or []),
            default_ratio=template.default_ratio,
            default_count=template.default_count,
            preview_asset_id=template.preview_asset_id,
            use_count=template.use_count,
            is_builtin=template.is_builtin,
            created_at=template.created_at.isoformat(),
        )


class RenderIn(BaseModel):
    values: dict[str, str] = {}


class RenderOut(BaseModel):
    prompt: str
    negative_prompt: str | None
