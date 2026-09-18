"""自建网关能力探测：接入前先拿事实，别拿真实任务去试错。

探测四件事：
  1. /models 列表          —— 网关是否可达、有哪些模型
  2. /chat/completions + 工具 —— 规划模型是否支持 function calling（对话链路硬门槛）
  3. /images/generations   —— 文生图是否可用、接受哪些尺寸档、返回 b64_json 还是 url
  4. /images/edits         —— 图生图是否可用（不可用则改图类工具会明确报错）

用法（容器内跑，凭据从环境变量读，避免写死在命令行历史里）：
  docker run --rm --network host \
    -e PROBE_BASE_URL=http://keepgulp.com:8002/v1 \
    -e PROBE_API_KEY=sk-xxx \
    -e PROBE_CHAT_MODEL=kimi-k3 \
    -e PROBE_IMAGE_MODEL=hunyuan-image-alpha \
    -v "$PWD/backend/scripts/probe_gateway.py:/tmp/probe.py:ro" \
    ai-retouch-agent-app python /tmp/probe.py
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import sys

import httpx
from PIL import Image

BASE = (os.environ.get("PROBE_BASE_URL") or "").rstrip("/")
KEY = os.environ.get("PROBE_API_KEY") or ""
CHAT_MODEL = os.environ.get("PROBE_CHAT_MODEL") or ""
IMAGE_MODEL = os.environ.get("PROBE_IMAGE_MODEL") or ""
TIMEOUT = 120.0

# 生图候选档位：覆盖方 / 横 / 竖三个方向，看网关实际认哪些
CANDIDATE_SIZES = ["1024x1024", "1536x1024", "1024x1536", "1080x1350", "1080x1920"]

TOOL = {
    "type": "function",
    "function": {
        "name": "adjust_image",
        "description": "调整图层亮度",
        "parameters": {
            "type": "object",
            "properties": {"brightness": {"type": "number", "minimum": -1, "maximum": 1}},
            "required": ["brightness"],
        },
    },
}

results: list[tuple[bool, str]] = []


def report(ok: bool, msg: str) -> None:
    results.append((ok, msg))
    mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
    print(f"  {mark} {msg}")


def headers() -> dict:
    return {"Authorization": f"Bearer {KEY}"}


async def probe_models(client: httpx.AsyncClient) -> list[str]:
    print("\n[1] /models 可达性与模型清单")
    if not BASE or not KEY:
        report(False, "缺少 PROBE_BASE_URL / PROBE_API_KEY")
        return []
    response = await client.get(f"{BASE}/models")
    if response.status_code != 200:
        report(False, f"/models HTTP {response.status_code}：{response.text[:120]}")
        return []
    models = [m.get("id", "") for m in response.json().get("data", [])]
    report(True, f"可达，共 {len(models)} 个模型")
    print(f"      样例：{models[:12]}")
    return models


async def probe_tool_calling(client: httpx.AsyncClient) -> bool:
    print("\n[2] /chat/completions 是否支持 function calling")
    if not CHAT_MODEL:
        report(False, "未设置 PROBE_CHAT_MODEL，跳过")
        return False
    response = await client.post(
        f"{BASE}/chat/completions",
        headers=headers(),
        json={
            "model": CHAT_MODEL,
            "messages": [{"role": "user", "content": "把图片调亮 0.2"}],
            "tools": [TOOL],
            "tool_choice": "auto",
            "temperature": 0,
            # 推理模型（如 kimi-k3）的思考过程也计入 completion tokens，
            # 预算太小会先被截断、永远走不到 tool_calls，造成误报
            "max_tokens": 4000,
        },
    )
    if response.status_code != 200:
        report(False, f"HTTP {response.status_code}：{response.text[:160]}")
        return False
    message = response.json()["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if not calls:
        report(False, f"模型返回了文本而不是工具调用：{str(message.get('content'))[:100]}")
        return False
    fn = calls[0]["function"]
    report(True, f"支持。模型调用了 {fn['name']}，参数 {fn.get('arguments')}")
    return True


async def probe_generation(client: httpx.AsyncClient) -> list[str]:
    print("\n[3] /images/generations 文生图")
    if not IMAGE_MODEL:
        report(False, "未设置 PROBE_IMAGE_MODEL，跳过")
        return []
    accepted: list[str] = []
    response_format = None
    for size in CANDIDATE_SIZES:
        response = await client.post(
            f"{BASE}/images/generations",
            headers=headers(),
            json={"model": IMAGE_MODEL, "prompt": "一只橘猫", "n": 1, "size": size},
        )
        if response.status_code != 200:
            detail = str(response.text)[:90]
            print(f"      {size:<12} HTTP {response.status_code}  {detail}")
            continue
        item = (response.json().get("data") or [{}])[0]
        kind = "b64_json" if item.get("b64_json") else ("url" if item.get("url") else "未知")
        response_format = response_format or kind
        accepted.append(size)
        print(f"      {size:<12} HTTP 200  返回 {kind}")
    if accepted:
        report(True, f"文生图可用，接受档位：{', '.join(accepted)}；返回形态 {response_format}")
    else:
        report(False, "所有候选档位都被拒绝，需核对网关支持的 model 与 size")
    return accepted


async def probe_edits(client: httpx.AsyncClient) -> bool:
    print("\n[4] /images/edits 图生图（dataURI + JSON）")
    if not IMAGE_MODEL:
        report(False, "未设置 PROBE_IMAGE_MODEL，跳过")
        return False
    image = Image.new("RGB", (8, 8), (20, 120, 220))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()

    response = await client.post(
        f"{BASE}/images/edits",
        headers=headers(),
        json={"model": IMAGE_MODEL, "prompt": "改成红色", "n": 1, "size": "1024x1024", "image": uri},
    )
    if response.status_code == 200:
        report(True, "图生图可用（改图类工具全部可用）")
        return True
    report(False, f"HTTP {response.status_code}：{response.text[:160]}")
    print("      → 图生图不可用时：replace_background / replace_region / upscale /")
    print("        erase_region 会明确报错；文生图与画布类工具不受影响。")
    return False


async def main() -> int:
    if not BASE or not KEY:
        print("请设置 PROBE_BASE_URL 与 PROBE_API_KEY 环境变量")
        return 2
    print(f"网关 {BASE}")
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        await probe_models(client)
        chat_ok = await probe_tool_calling(client)
        sizes = await probe_generation(client)
        edits_ok = await probe_edits(client)

    print("\n———— 结论 ————")
    print(f"  对话链路（规划模型 function calling）：{'可用' if chat_ok else '不可用'}")
    print(f"  生图链路（文生图）：{'可用' if sizes else '不可用'}")
    print(f"  生图链路（图生图）：{'可用' if edits_ok else '不可用'}")
    if sizes:
        print(f"  建议配置 IMAGES_SIZES={','.join(sizes)}")
    failed = [msg for ok, msg in results if not ok]
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
