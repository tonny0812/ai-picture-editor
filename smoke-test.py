"""本地 Docker 部署冒烟验证。

覆盖：登录 → mock 文生图 → 建会话 → 同步工具（flip_layer）→ 异步工具（adjust_image）
→ 撤销/重做 → 历史 → ZIP 导出 → 自然语言对话降级 → 越权防护。

需在能访问 localhost:7302 / localhost:7313 的环境运行（容器 host 网络即可）：
    docker run --rm --network host -v "$PWD/smoke-test.py:/tmp/smoke.py:ro" \
        ai-retouch-agent-app python /tmp/smoke.py
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
import uuid
import zipfile

import httpx

BASE = "http://127.0.0.1:7302"
USER = {"username": "smoketest", "password": "smoke1234"}
TERMINAL = {"succeeded", "failed", "canceled"}

passed: list[str] = []
failed: list[str] = []


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  \033[32m✓\033[0m {msg}")


def bad(msg: str) -> None:
    failed.append(msg)
    print(f"  \033[31m✗\033[0m {msg}")


def check(cond: bool, msg: str) -> bool:
    ok(msg) if cond else bad(msg)
    return cond


async def poll_run(client: httpx.AsyncClient, run_id: str, timeout: float = 120.0) -> dict:
    """轮询到终态。同步工具返回时通常已是 succeeded。"""
    deadline = time.monotonic() + timeout
    while True:
        r = await client.get(f"/api/runs/{run_id}")
        r.raise_for_status()
        payload = r.json()
        if payload["status"] in TERMINAL:
            return payload
        if time.monotonic() > deadline:
            raise TimeoutError(f"任务 {run_id} 超时，最后状态 {payload['status']}")
        await asyncio.sleep(0.5)


async def wait_message_settles(client: httpx.AsyncClient, sid: str, timeout: float = 120.0) -> dict:
    """等待会话最近一轮对话进入终态。"""
    deadline = time.monotonic() + timeout
    while True:
        r = await client.get(f"/api/sessions/{sid}/messages")
        r.raise_for_status()
        turns = r.json()
        if turns and turns[-1]["status"] in TERMINAL:
            return turns[-1]
        if time.monotonic() > deadline:
            raise TimeoutError(f"对话未收敛，最后 {turns[-1]['status'] if turns else '无'}")
        await asyncio.sleep(0.5)


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0, trust_env=False) as c:
        # 1) 认证
        r = await c.post("/api/auth/register", json=USER)
        if r.status_code == httpx.codes.CONFLICT:
            r = await c.post("/api/auth/login", json=USER)
        if not check(r.status_code in (200, 201), f"注册/登录成功（{r.status_code}）"):
            print(r.text)
            return 1

        # 2) mock 文生图，取候选图作为后续编辑素材
        r = await c.post(
            "/api/generations",
            json={"prompt": "白色背景上的橙色运动鞋，电商主图", "ratio": "4:5", "count": 2},
        )
        check(r.status_code == httpx.codes.ACCEPTED, f"文生图任务入队（{r.status_code}）")
        gen = await poll_run(c, r.json()["id"])
        check(gen["status"] == "succeeded", f"文生图完成，状态 {gen['status']}")
        candidates = gen["candidates"]
        check(len(candidates) == 2, f"候选图 {len(candidates)} 张")
        if not candidates:
            return 1
        asset_id = candidates[0]["id"]
        check(
            (candidates[0]["width"], candidates[0]["height"]) == (1080, 1350),
            f"尺寸 {candidates[0]['width']}x{candidates[0]['height']} 符合 4:5",
        )

        # 3) 签名 URL 可匿名下载
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as anon:
            img = await anon.get(candidates[0]["url"])
        check(
            img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n",
            f"签名 URL 可下载 PNG（{len(img.content)} 字节）",
        )

        # 4) 建会话
        r = await c.post(
            "/api/sessions",
            json={"current_asset_id": asset_id, "asset_ids": [a["id"] for a in candidates]},
        )
        check(r.status_code == httpx.codes.CREATED, f"创建编辑会话（{r.status_code}）")
        sid = r.json()["id"]
        base_revision = r.json()["revision"]

        # 5) 同步工具：flip_layer 即时生效，不需 worker
        r = await c.post(
            f"/api/sessions/{sid}/tools",
            json={"tool": "flip_layer", "params": {"direction": "horizontal"}},
        )
        check(r.status_code == httpx.codes.ACCEPTED, f"同步工具 flip_layer 受理（{r.status_code}）")
        run = (await poll_run(c, r.json()["run"]["id"])) if r.status_code == 202 else r.json()["run"]
        check(run["status"] == "succeeded", f"flip_layer 执行成功（{run['status']}）")

        # 6) 异步工具：adjust_image 走队列 + worker
        r = await c.post(
            f"/api/sessions/{sid}/tools",
            json={"tool": "adjust_image", "params": {"brightness": 0.2, "contrast": 0.1}},
        )
        check(r.status_code == httpx.codes.ACCEPTED, f"异步工具 adjust_image 入队（{r.status_code}）")
        run = await poll_run(c, r.json()["run"]["id"])
        check(run["status"] == "succeeded", f"adjust_image 完成（{run['status']}）")

        # 7) 会话状态推进
        r = await c.get(f"/api/sessions/{sid}")
        detail = r.json()
        check(
            detail["revision"] > base_revision,
            f"会话 revision {base_revision} → {detail['revision']}（画布已更新）",
        )
        check(int(detail["history_seq"]) >= 2, f"历史序号推进到 {detail['history_seq']}")

        # 8) 撤销 / 重做
        r = await c.post(f"/api/sessions/{sid}/undo")
        check(r.status_code == 200, f"撤销可用（{r.status_code}）")
        r = await c.post(f"/api/sessions/{sid}/redo")
        check(r.status_code == 200, f"重做可用（{r.status_code}）")

        # 9) 历史与导出
        r = await c.get(f"/api/sessions/{sid}/history")
        check(r.status_code == 200 and len(r.json()) >= 2, f"历史记录 {len(r.json())} 条")
        r = await c.post(f"/api/sessions/{sid}/exports", json={"asset_ids": [asset_id]})
        is_zip = r.status_code == 200 and r.content[:2] == b"PK"
        check(is_zip, f"ZIP 导出可用（{r.status_code}，{len(r.content)} 字节）")
        if is_zip:
            names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
            check(len(names) >= 1, f"ZIP 内含 {names[0]} 等 {len(names)} 个文件")

        # 10) 参数校验：非法参数应被拒
        r = await c.post(
            f"/api/sessions/{sid}/tools",
            json={"tool": "flip_layer", "params": {"direction": "diagonal"}},
        )
        check(
            r.status_code == 422,
            f"非法参数被拒（{r.status_code}）",
        )
        r = await c.post(
            f"/api/sessions/{sid}/tools", json={"tool": "not_a_tool", "params": {}}
        )
        check(r.status_code == httpx.codes.NOT_FOUND, f"未注册工具被拒（{r.status_code}）")

        # 11) 自然语言对话：未配 DASHSCOPE_API_KEY 时应干净报错而非 500
        r = await c.post(
            f"/api/sessions/{sid}/messages", json={"text": "把背景换成海滩"}
        )
        if r.status_code < 500:
            ok(f"对话接口未崩（{r.status_code}）：{(r.json().get('detail') or '')[:60]}")
        else:
            bad(f"对话接口 5xx（{r.status_code}）：{r.text[:120]}")

        # 12) 越权防护：他人访问该会话应 404
        other = {"username": f"other_{uuid.uuid4().hex[:8]}", "password": "other12345"}
        await c.post("/api/auth/register", json=other)
        r = await c.get(f"/api/sessions/{sid}")
        check(r.status_code == 404, f"他人读取会话被拒（{r.status_code}）")
        r = await c.post(f"/api/sessions/{sid}/tools", json={"tool": "flip_layer", "params": {"direction": "vertical"}})
        check(r.status_code == 404, f"他人改写会话被拒（{r.status_code}）")

    print(f"\n通过 {len(passed)} 项，失败 {len(failed)} 项")
    for item in failed:
        print(f"  失败：{item}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
