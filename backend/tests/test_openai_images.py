"""openai_images 的单元测试：不触网，覆盖尺寸选档、裁切与多图返回兼容。"""

import base64
import io

import pytest
from PIL import Image

from app.llm_config import ResolvedLlmConfig
from app.providers.base import GenerateRequest, ProviderError
from app.providers.openai_images import (
    OpenAIImagesProvider,
    data_uri,
    fit_image,
    parse_response,
    parse_sizes,
    pick_size,
)


def _config(**overrides) -> ResolvedLlmConfig:
    return ResolvedLlmConfig(
        images_base_url="https://gw.example.com/v1",
        images_api_key="sk-test",
        images_model="test-image-model",
        **overrides,
    )


def _png(width: int, height: int, color=(200, 30, 30)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_parse_sizes_ignores_blank_and_invalid_entries():
    assert parse_sizes(" 1024x1024, 1536*1024 ,bad,,0x100") == [
        (1024, 1024),
        (1536, 1024),
    ]
    assert parse_sizes("") == []
    assert parse_sizes("x") == []


def test_pick_size_prefers_closest_aspect_ratio():
    sizes = parse_sizes("1024x1024,1536x1024,1024x1536")
    # 4:5 竖图：1536x1024 是横的，1024x1536 是竖的，应选竖档
    assert pick_size(sizes, 1080, 1350) == "1024x1536"
    # 1:1 方图
    assert pick_size(sizes, 1024, 1024) == "1024x1024"
    # 16:9 横图：1536x1024 是 3:2，比 1024x1024 的 1:1 更接近 16:9
    assert pick_size(sizes, 1920, 1080) == "1536x1024"


def test_pick_size_breaks_ties_toward_larger_resolution():
    sizes = parse_sizes("512x512,1024x1024")
    assert pick_size(sizes, 1000, 1000) == "1024x1024"


def test_fit_image_crops_to_target_aspect_then_resizes():
    # 3:2 横图裁成 1:1，应只保留中间竖条
    raw = _png(1500, 1000)
    out = fit_image(raw, 1000, 1000)
    assert Image.open(io.BytesIO(out)).size == (1000, 1000)


def test_fit_image_passthrough_when_target_unknown_or_equal():
    raw = _png(300, 200)
    assert fit_image(raw, None, None) is raw
    assert fit_image(raw, 300, 200) is raw


def test_data_uri_is_decodable_base64_png():
    raw = _png(4, 4)
    uri = data_uri(raw)
    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == raw


def test_parse_response_surfaces_gateway_error_message():
    import httpx

    request = httpx.Request("POST", "http://gw")
    ok = httpx.Response(200, json={"data": [{"b64_json": "abc"}]}, request=request)
    assert parse_response(ok) == {"data": [{"b64_json": "abc"}]}

    err = httpx.Response(
        400, json={"error": {"message": "size 不被支持"}}, request=request
    )
    with pytest.raises(Exception, match="size 不被支持"):
        parse_response(err)

    non_json = httpx.Response(502, text="bad gateway", request=request)
    with pytest.raises(Exception, match="非 JSON"):
        parse_response(non_json)


# ---------------------------------------------------------- 一次返回多张的兼容


async def test_extract_all_keeps_every_b64_item():
    """data 数组里有几张就返回几张，不再只取第一张。"""
    provider = OpenAIImagesProvider(_config())
    frames = [_png(8, 8), _png(9, 9), _png(10, 10)]
    body = {"data": [{"b64_json": base64.b64encode(f).decode()} for f in frames]}

    images = await provider._extract_all(body)

    assert images == frames


async def test_extract_all_accepts_bare_strings_and_links(monkeypatch):
    """聚合网关常见两种简写：数组项直接是 base64 串或 http 链接。"""
    provider = OpenAIImagesProvider(_config())
    raw = _png(6, 6)
    linked = _png(7, 7)

    async def fake_download(url: str) -> bytes:
        assert url == "https://cdn.example.com/a.png"
        return linked

    monkeypatch.setattr(provider, "_download", fake_download)
    body = {"data": [data_uri(raw), "https://cdn.example.com/a.png"]}

    assert await provider._extract_all(body) == [raw, linked]


async def test_extract_all_skips_broken_items_but_keeps_the_rest():
    """个别项坏掉不影响其余结果：可用几张就返回几张。"""
    provider = OpenAIImagesProvider(_config())
    good = _png(5, 5)
    body = {"data": [{"revised_prompt": "没有图"}, {"b64_json": base64.b64encode(good).decode()}]}

    assert await provider._extract_all(body) == [good]


async def test_extract_all_raises_when_nothing_usable():
    provider = OpenAIImagesProvider(_config())

    with pytest.raises(ProviderError):
        await provider._extract_all({"data": []})
    with pytest.raises(ProviderError):
        await provider._extract_all({"data": [{"revised_prompt": "无图"}]})


async def test_extract_all_falls_back_to_choices_key(monkeypatch):
    """部分网关把结果放在 choices 而不是 data。"""
    provider = OpenAIImagesProvider(_config())
    raw = _png(4, 6)
    body = {"choices": [{"image_url": {"url": "https://cdn.example.com/b.png"}}]}

    async def fake_download(_: str) -> bytes:
        return raw

    monkeypatch.setattr(provider, "_download", fake_download)

    assert await provider._extract_all(body) == [raw]


async def test_generate_flattens_multi_image_responses(monkeypatch):
    """count=1 但网关回 2 张：两张都要保留，不能再丢。"""
    provider = OpenAIImagesProvider(_config())
    first, second = _png(10, 10), _png(10, 10, (10, 200, 10))

    async def two_images(path: str, payload: dict) -> list[bytes]:
        assert path == "/images/generations"
        return [first, second]

    monkeypatch.setattr(provider, "_images_once", two_images)

    images = await provider.generate(GenerateRequest(prompt="杯子", width=10, height=10, count=1))

    assert images == [first, second]


async def test_generate_flatmaps_multiple_requests(monkeypatch):
    """count=2 且每次各回 2 张：展平为 4 张，顺序稳定。"""
    provider = OpenAIImagesProvider(_config())
    calls: list[int] = []

    async def two_images(path: str, payload: dict) -> list[bytes]:
        calls.append(1)
        return [_png(10, 10, (index, 10, 10)) for index in (len(calls), len(calls) + 10)]

    monkeypatch.setattr(provider, "_images_once", two_images)

    images = await provider.generate(GenerateRequest(prompt="杯子", width=10, height=10, count=2))

    assert len(calls) == 2
    assert len(images) == 4
