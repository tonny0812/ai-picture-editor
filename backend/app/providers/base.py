from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

ProgressCallback = Callable[[int, str], Awaitable[None]]


class ProviderError(Exception):
    """模型服务不可用或返回失败。

    `args[0]` 是给用户看的一句话摘要；detail 是排查上下文（上游状态码、
    原始响应、请求摘要、排查建议），两者会一起写进任务失败原因里。
    """

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    @property
    def report(self) -> str:
        """摘要 + 详情，用于落库和展示。"""
        return f"{self.message}\n{self.detail}" if self.detail else self.message


@dataclass(frozen=True)
class GenerateRequest:
    prompt: str
    width: int
    height: int
    count: int = 1
    negative_prompt: str | None = None
    seed: int | None = None
    # 参考图以原始字节传入，由各 adapter 决定编码方式
    references: list[bytes] = field(default_factory=list)


@dataclass(frozen=True)
class EditRequest:
    prompt: str
    image: bytes
    count: int = 1
    width: int | None = None
    height: int | None = None
    negative_prompt: str | None = None


class ImageProvider(Protocol):
    name: str

    async def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None = None
    ) -> list[bytes]:
        """返回 count 张图片的原始字节。失败时抛出 ProviderError。"""
        ...

    async def edit(
        self, request: EditRequest, on_progress: ProgressCallback | None = None
    ) -> list[bytes]:
        """按提示词改已有图片。width/height 有值时同时改画幅，用于扩图。"""
        ...

    async def upscale(
        self, image: bytes, scale: int, on_progress: ProgressCallback | None = None
    ) -> bytes:
        """提高分辨率，不改变构图。"""
        ...
