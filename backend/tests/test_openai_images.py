"""openai_images 纯函数辅助的单元测试：不触网，覆盖尺寸选档与裁切逻辑。"""

import base64
import io

import pytest
from PIL import Image

from app.providers.openai_images import (
    data_uri,
    fit_image,
    parse_response,
    parse_sizes,
    pick_size,
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
