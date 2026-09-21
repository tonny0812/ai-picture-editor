"""openai_images 的单元测试：不触网，覆盖尺寸选档、裁切、多图返回与错误透传。"""

import asyncio
import base64
import io

import httpx
import pytest
from PIL import Image

from app.llm_config import ResolvedLlmConfig
from app.providers.base import GenerateRequest, ProviderError
from app.providers.openai_images import (
    OpenAIImagesProvider,
    _extract_message,
    build_upstream_error,
    data_uri,
    fit_image,
    parse_response,
    parse_sizes,
    pick_size,
)

_REQUEST = httpx.Request("POST", "https://gw.example.com/v1/images/generations")


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


# ------------------------------------------------------------ 错误详情要原样透出


def test_upstream_error_keeps_raw_body_and_request_brief():
    """网关压缩成一句 upstream 400 时，原文、请求摘要、排查建议都要留在错误里。"""
    error = build_upstream_error(
        400,
        '{"error":{"message":"upstream 400","type":"upstream_error","code":400}}',
        "POST /images/generations · 模型 hunyuan-image-alpha · 尺寸 1024x1024",
    )

    assert "upstream 400" in error.message
    assert "HTTP 400" in error.message
    assert "网关原文" in error.detail
    assert "upstream_error" in error.detail
    assert "请求摘要" in error.detail
    assert "排查建议" in error.detail
    # 首行摘要不重复出现在详情里
    assert error.report.count("upstream 400") >= 2


def test_upstream_error_reads_plain_text_body():
    error = build_upstream_error(502, "bad gateway")
    assert "非 JSON" in error.message
    assert "bad gateway" in error.report


def test_upstream_error_hint_differs_by_status():
    assert "限流" in build_upstream_error(429, '{"error":{"message":"slow down"}}').detail
    assert "密钥" in build_upstream_error(401, '{"error":{"message":"nope"}}').detail
    assert "模型名" in build_upstream_error(404, '{"error":{"message":"no model"}}').detail


def test_extract_message_understands_various_shapes():
    assert _extract_message({"error": {"message": "坏了"}}) == "坏了"
    assert _extract_message({"error": "直接字符串"}) == "直接字符串"
    assert _extract_message({"message": "平铺字段"}) == "平铺字段"
    assert _extract_message({"error": {"code": 1234}}) == "1234"
    assert _extract_message("纯文本") == "纯文本"
    assert _extract_message([]) == ""
    assert _extract_message({"data": []}) == ""


def test_parse_response_rejects_non_json_success():
    with pytest.raises(ProviderError, match="非 JSON"):
        parse_response(httpx.Response(200, text="not json", request=_REQUEST))


def test_parse_response_surfaces_error_inside_200_body():
    body = {"error": {"message": "配额不足"}}
    with pytest.raises(ProviderError, match="配额不足"):
        parse_response(httpx.Response(200, json=body, request=_REQUEST))


# -------------------------------------------------------------- 重试与并发策略


def _ok_response() -> httpx.Response:
    encoded = base64.b64encode(_png(8, 8)).decode()
    return httpx.Response(200, json={"data": [{"b64_json": encoded}]}, request=_REQUEST)


async def test_retries_on_429_then_succeeds(monkeypatch):
    statuses = [429, 200]

    async def fake_post(url, json=None):  # noqa: A002 - 与 httpx 参数名保持一致
        status = statuses.pop(0)
        if status == 200:
            return _ok_response()
        return httpx.Response(status, json={"error": {"message": "rate limited"}}, request=_REQUEST)

    async def no_sleep(*_: object) -> None:
        return None

    provider = OpenAIImagesProvider(_config())
    provider._retries = 2
    monkeypatch.setattr(provider._client, "post", fake_post)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    body = await provider._post("/images/generations", {"model": "m", "prompt": "p", "n": 1})

    assert "data" in body
    assert statuses == []


async def test_does_not_retry_on_400(monkeypatch):
    """400 是请求本身有问题，重试无意义——只发一次，把网关原文报出来。"""
    attempts: list[int] = []

    async def fake_post(url, json=None):  # noqa: A002
        attempts.append(1)
        return httpx.Response(400, json={"error": {"message": "upstream 400"}}, request=_REQUEST)

    provider = OpenAIImagesProvider(_config())
    provider._retries = 2
    monkeypatch.setattr(provider._client, "post", fake_post)

    with pytest.raises(ProviderError) as caught:
        await provider._post("/images/generations", {"model": "m", "prompt": "p", "n": 1})

    assert len(attempts) == 1
    assert "upstream 400" in caught.value.message


async def test_connection_failure_is_reported_with_endpoint(monkeypatch):
    async def fake_post(url, json=None):  # noqa: A002
        raise httpx.ConnectError("connection refused")

    provider = OpenAIImagesProvider(_config())
    provider._retries = 0
    monkeypatch.setattr(provider._client, "post", fake_post)

    with pytest.raises(ProviderError) as caught:
        await provider._post("/images/edits", {"model": "m", "prompt": "p", "n": 1})

    assert "连接失败" in caught.value.message
    assert "/images/edits" in caught.value.message


async def test_parallel_requests_respect_concurrency_cap(monkeypatch):
    """一次要 4 张时并发不超过配置上限，避免把网关打回 400/429。"""
    live = 0
    peak = 0

    async def fake_post(url, json=None):  # noqa: A002
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.02)
        live -= 1
        return _ok_response()

    provider = OpenAIImagesProvider(_config())
    provider._retries = 0
    provider._gate = asyncio.Semaphore(2)
    monkeypatch.setattr(provider._client, "post", fake_post)

    images = await provider.generate(
        GenerateRequest(prompt="杯子", width=8, height=8, count=4)
    )

    assert len(images) == 4
    assert peak <= 2
