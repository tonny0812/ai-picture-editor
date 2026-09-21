"""LLM 配置接口的数据契约。

密钥字段只写不读：请求里传新值即变更、传空串即清除、不传即不变；
响应里永远是打码后的展示值。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LlmConfigIn(BaseModel):
    """PUT / llm-config 与 test 的请求体。全部字段可选。"""

    planner_base_url: str | None = Field(default=None, max_length=512)
    planner_api_key: str | None = Field(default=None, max_length=256)
    planner_model: str | None = Field(default=None, max_length=128)
    planner_timeout: int | None = Field(default=None, ge=5, le=600)
    planner_max_retries: int | None = Field(default=None, ge=0, le=10)
    images_base_url: str | None = Field(default=None, max_length=512)
    images_api_key: str | None = Field(default=None, max_length=256)
    images_model: str | None = Field(default=None, max_length=128)
    images_sizes: str | None = Field(default=None, max_length=256)
    image_provider: Literal["mock", "dashscope", "openai"] | None = None
    lock_image_provider: bool | None = None
    include_images: bool = True  # 仅 test 请求消费

    @field_validator(
        "planner_base_url",
        "images_base_url",
        "planner_model",
        "images_model",
        "images_sizes",
    )
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("planner_base_url", "images_base_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("必须是 http/https 地址")
        return value


class EffectiveView(BaseModel):
    """生效配置（key 打码）。source 标明每个字段来自哪一层：env / global / user。"""

    planner_base_url: str
    planner_model: str
    planner_timeout: float
    planner_max_retries: int
    planner_api_key_masked: str
    images_base_url: str
    images_model: str
    images_sizes: str
    images_api_key_masked: str
    image_provider: str
    lock_image_provider: bool
    source: dict[str, str]
    overridden: list[str]


class OverridesView(BaseModel):
    values: dict[str, object]
    updated_at: str | None


class MeLlmConfigOut(BaseModel):
    effective: EffectiveView
    overrides: OverridesView


class TestOut(BaseModel):
    fingerprint: str
    planner: dict[str, object]
    images: dict[str, object]
