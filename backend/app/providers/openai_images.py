"""OpenAI 兼容 images API 适配器。

面向自建 / 聚合网关（如 OpenLux）。文生图走 /images/generations；
图生图走 /images/edits，用 JSON + dataURI 而非 multipart——聚合网关普遍
不认 multipart（实测 multipart 会被当 utf-8 解开导致二进制炸裂）。

两点约定：
- 不做端点间静默回退。图生图失败时明确抛错并说明原因，避免"看起来改了
  图、实际是重新生成"的假成功。
- 一次请求可能返回多张（多数网关对 n 的支持不一致：有的忽略 n 各回多张，
  有的把多张塞进 data 数组）。返回多少就保留多少，绝不只取第一张——
  上层按语义决定是全进候选墙还是只取首张。

网关通常只认固定尺寸档位（如 1536x1024）。配置 IMAGES_SIZES 后按最近比例
选档，下载后中心裁切并缩放回目标尺寸，保证与项目"素材即画布尺寸"的约定一致。
"""

import asyncio
import base64
import io
import logging

import httpx
from PIL import Image

from app.llm_config import ResolvedLlmConfig
from app.providers.base import (
    EditRequest,
    GenerateRequest,
    ImageProvider,
    ProgressCallback,
    ProviderError,
)

_GENERATIONS = "/images/generations"
_EDITS = "/images/edits"
_TIMEOUT = 300.0
_DOWNLOAD_TIMEOUT = 60.0

logger = logging.getLogger(__name__)


class OpenAIImagesProvider(ImageProvider):
    name = "openai"

    def __init__(self, config: ResolvedLlmConfig) -> None:
        base_url = config.images_base_url
        api_key = config.images_api_key
        if not base_url or not api_key:
            raise ProviderError(
                "未配置图像网关：请填写 IMAGES_BASE_URL / IMAGES_API_KEY（或 PLANNER_*）"
            )
        if not config.images_model:
            raise ProviderError("未配置 IMAGES_MODEL，无法指定生图模型")

        self._base = base_url.rstrip("/")
        self._model = config.images_model
        self._sizes = parse_sizes(config.images_sizes)
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=_TIMEOUT
        )

    async def generate(
        self, request: GenerateRequest, on_progress: ProgressCallback | None = None
    ) -> list[bytes]:
        if on_progress:
            await on_progress(10, "提交生成")
        payload = self._payload(request.prompt, request.negative_prompt)
        size = self._pick_size(request.width, request.height)
        if size:
            payload["size"] = size
        groups = await asyncio.gather(
            *(self._images_once(_GENERATIONS, payload) for _ in range(request.count))
        )
        raws = _flatten(groups, request.count)
        if on_progress:
            await on_progress(85, "处理结果")
        return [fit_image(raw, request.width, request.height) for raw in raws]

    async def edit(
        self, request: EditRequest, on_progress: ProgressCallback | None = None
    ) -> list[bytes]:
        if on_progress:
            await on_progress(15, "提交编辑")
        payload = self._payload(request.prompt, request.negative_prompt)
        payload["image"] = data_uri(request.image)
        size = None
        if request.width and request.height:
            size = self._pick_size(request.width, request.height)
            if size:
                payload["size"] = size
        groups = await asyncio.gather(
            *(self._images_once(_EDITS, payload) for _ in range(request.count))
        )
        raws = _flatten(groups, request.count)
        if on_progress:
            await on_progress(85, "处理结果")
        target_w = request.width or None
        target_h = request.height or None
        return [fit_image(raw, target_w, target_h) for raw in raws]

    async def upscale(
        self, image: bytes, scale: int, on_progress: ProgressCallback | None = None
    ) -> bytes:
        source = Image.open(io.BytesIO(image))
        results = await self.edit(
            EditRequest(
                prompt="提高清晰度，保持主体、构图和颜色不变，不要添加新元素。",
                image=image,
                width=source.width * scale,
                height=source.height * scale,
            ),
            on_progress,
        )
        return results[0]

    def _payload(self, prompt: str, negative_prompt: str | None) -> dict:
        text = prompt if not negative_prompt else f"{prompt}\n避免：{negative_prompt}"
        return {"model": self._model, "prompt": text, "n": 1}

    async def _images_once(self, path: str, payload: dict) -> list[bytes]:
        data = await self._post(path, payload)
        return await self._extract_all(data)

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            response = await self._client.post(self._base + path, json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(f"图像网关连接失败（{path}）：{exc}") from exc
        return parse_response(response)

    async def _extract_all(self, data: dict) -> list[bytes]:
        """取出响应里的全部图片并保持顺序。

        兼容三种返回形态：
        - data/choices 数组内每项是 dict，带 b64_json / b64 / url / image_url
        - 数组项直接是 base64 字符串（部分聚合网关如此）
        - 数组项直接是 http 链接

        个别项坏掉不影响其余结果：只要还有一张可用就返回，坏项记日志。
        """
        items = data.get("data") or data.get("choices") or []
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or not items:
            raise ProviderError("图像网关返回成功但没有图片数据")

        results = await asyncio.gather(
            *(self._one_image(item) for item in items), return_exceptions=True
        )
        images = [item for item in results if isinstance(item, bytes)]
        failures = [str(item) for item in results if isinstance(item, Exception)]
        if not images:
            raise ProviderError(failures[0] if failures else "图像网关返回格式无法识别")
        if failures:
            logger.warning(
                "图像网关有 %d 张结果解析失败（已跳过，其余 %d 张保留）：%s",
                len(failures),
                len(images),
                "；".join(failures[:3]),
            )
        return images

    async def _one_image(self, item: object) -> bytes:
        if isinstance(item, str):
            text = item.strip()
            if text.startswith(("http://", "https://")):
                return await self._download(text)
            return decode_base64(text)
        if not isinstance(item, dict):
            raise ProviderError(f"图像网关返回了无法识别的结果项：{type(item).__name__}")

        encoded = item.get("b64_json") or item.get("b64") or item.get("image_base64")
        if isinstance(encoded, str) and encoded:
            return decode_base64(encoded)

        url = item.get("url") or item.get("image_url")
        if isinstance(url, dict):
            url = url.get("url")
        if isinstance(url, str) and url:
            return await self._download(url)
        raise ProviderError("图像网关返回格式中既没有 b64_json 也没有 url")

    async def _download(self, url: str) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise ProviderError(f"生成结果下载失败：{exc}") from exc
        if response.status_code != httpx.codes.OK:
            raise ProviderError(f"生成结果下载失败：HTTP {response.status_code}")
        return response.content

    def _pick_size(self, width: int | None, height: int | None) -> str | None:
        if not self._sizes or not width or not height:
            return None
        return pick_size(self._sizes, width, height)


def _flatten(groups: list[list[bytes]], requested: int) -> list[bytes]:
    """把多次请求的结果摊平。网关一次回多张时全部保留，只记一条日志说明差异。"""
    images = [raw for group in groups for raw in group]
    if len(images) > requested:
        logger.info(
            "图像网关一次返回多张：请求 %d 张，实际 %d 张，全部保留并作为候选",
            requested,
            len(images),
        )
    return images


def decode_base64(encoded: str) -> bytes:
    """解 base64；兼容 dataURI 前缀与缺失的 padding。"""
    text = encoded.strip()
    if text.startswith("data:"):
        text = text.split(",", 1)[-1]
    text = text.strip()
    try:
        return base64.b64decode(text, validate=False)
    except (ValueError, TypeError) as exc:
        raise ProviderError("图像网关返回的 base64 无法解码") from exc


def parse_response(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderError(
            f"图像网关返回非 JSON 响应（HTTP {response.status_code}）"
        ) from exc

    if response.status_code != httpx.codes.OK:
        detail = body.get("error", {}).get("message") if isinstance(body, dict) else None
        raise ProviderError(
            detail or str(body)[:200] or f"图像网关错误 HTTP {response.status_code}"
        )
    if isinstance(body, dict) and body.get("error"):
        message = body["error"]
        raise ProviderError(
            message.get("message") if isinstance(message, dict) else str(message)
        )
    return body


def parse_sizes(text: str) -> list[tuple[int, int]]:
    """把 "1024x1024,1536x1024" 解析成尺寸列表；空白或非法项忽略。"""
    sizes: list[tuple[int, int]] = []
    for part in (text or "").split(","):
        part = part.strip().lower().replace("*", "x")
        if not part:
            continue
        width, _, height = part.partition("x")
        if width.isdigit() and height.isdigit() and int(width) > 0 and int(height) > 0:
            sizes.append((int(width), int(height)))
    return sizes


def pick_size(sizes: list[tuple[int, int]], width: int, height: int) -> str:
    """按长宽比距离选档，同分取分辨率更高的一档。"""
    target_ratio = width / height
    best = min(
        sizes,
        key=lambda size: (
            abs(size[0] / size[1] - target_ratio),
            -size[0] * size[1],
        ),
    )
    return f"{best[0]}x{best[1]}"


def data_uri(raw: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(raw).decode()}"


def fit_image(raw: bytes, width: int | None, height: int | None) -> bytes:
    """把网关返回的图规整到目标尺寸：中心裁切到目标比例后缩放。

    目标尺寸未知时原样返回；尺寸一致时跳过处理，避免无谓重编码。
    """
    if not width or not height:
        return raw
    image = Image.open(io.BytesIO(raw))
    if image.size == (width, height):
        return raw
    return _crop_and_resize(image, width, height)


def _crop_and_resize(image: Image.Image, width: int, height: int) -> bytes:
    source_w, source_h = image.size
    target_ratio = width / height
    source_ratio = source_w / source_h
    if source_ratio > target_ratio:
        crop_w = int(round(source_h * target_ratio))
        left = (source_w - crop_w) // 2
        box = (left, 0, left + crop_w, source_h)
    else:
        crop_h = int(round(source_w / target_ratio))
        top = (source_h - crop_h) // 2
        box = (0, top, source_w, top + crop_h)
    resized = image.crop(box).resize((width, height), Image.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()
