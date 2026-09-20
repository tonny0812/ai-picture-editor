"""LLM 配置的解析、存取、审计与测试连接。

解析顺序（核心约定，见 docs/LLM-CONFIG-DESIGN.md §4）：
    用户覆盖行 → 全局行 → .env / Settings 默认值

字段级 NULL 回落：行里某列是 NULL 就继续用下一层，因此用户只需覆盖
自己想改的字段。解析结果带 60s TTL 缓存，任何写入都会立刻失效缓存——
配置热生效（最多延迟一个 TTL，写操作后立即生效）。

⚠️ 队列是全局共享的：任务载荷只带 run_id，worker 执行时按 run.user_id
重新解析配置取 provider。绝不能把某个用户的 key 混进别人的任务。
"""

import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm_config import ResolvedLlmConfig, compatible_path, mask_secret
from app.models import LlmConfig, LlmConfigAudit
from app.services import crypto

logger = logging.getLogger(__name__)

CACHE_TTL = 60.0
TEST_INTERVAL = 60.0

# 可覆盖字段 → LlmConfig 列名（密钥列单独处理）
TEXT_FIELDS: dict[str, str] = {
    "planner_base_url": "planner_base_url",
    "planner_model": "planner_model",
    "images_base_url": "images_base_url",
    "images_model": "images_model",
    "images_sizes": "images_sizes",
    "image_provider": "image_provider",
}
INT_FIELDS: dict[str, str] = {
    "planner_timeout": "planner_timeout",
    "planner_max_retries": "planner_max_retries",
}
SECRET_FIELDS: dict[str, str] = {
    "planner_api_key": "planner_api_key_enc",
    "images_api_key": "images_api_key_enc",
}
ALL_FIELDS = {**TEXT_FIELDS, **INT_FIELDS, **SECRET_FIELDS}

_cache: dict[uuid.UUID, tuple[float, ResolvedLlmConfig]] = {}
_test_last: dict[uuid.UUID, float] = {}


class FieldLocked(Exception):
    """全局开启 lock_image_provider 后用户仍尝试覆盖 provider。"""


class UrlNotAllowed(ValueError):
    """用户级 base_url 指向内网 / 保留地址（SSRF 防护）。"""


def invalidate(user_id: uuid.UUID | None = None) -> None:
    """配置变更后调用。全清最简单也最安全——写操作本来就低频。"""
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


# ---------------------------------------------------------------- SSRF 防护


def ensure_public_url(url: str) -> None:
    """用户可填任意 base_url，服务端会拿它发请求——必须挡住内网探测。

    admin 配全局不做此限制（管理员本就可控整个部署）；此函数只用于用户级。
    IP 字面量直接判断，主机名解析后逐个地址判断。
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise UrlNotAllowed("URL 无法解析") from exc
    if parsed.scheme not in ("http", "https"):
        raise UrlNotAllowed("base_url 仅支持 http/https")
    host = parsed.hostname
    if not host:
        raise UrlNotAllowed("base_url 缺少主机名")

    try:
        candidates = [ipaddress.ip_address(host)]
    except ValueError:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UrlNotAllowed(f"主机无法解析：{host}") from exc
        candidates = [ipaddress.ip_address(info[4][0]) for info in infos]

    for ip in candidates:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UrlNotAllowed(f"base_url 不允许指向内网或保留地址：{host}")


# ---------------------------------------------------------------- 解析


def _env_raw() -> tuple[dict[str, object], dict[str, str]]:
    """第三层：.env 默认值。settings 是单例，测试里可以运行时改写。"""
    settings = get_settings()
    raw: dict[str, object] = {
        "planner_base_url": settings.planner_base_url,
        "planner_api_key": settings.planner_api_key,
        "planner_model": settings.planner_model,
        "planner_timeout": settings.planner_timeout,
        "planner_max_retries": settings.planner_max_retries,
        "images_base_url": settings.images_base_url,
        "images_api_key": settings.images_api_key,
        "images_model": settings.images_model,
        "images_sizes": settings.images_sizes,
        "image_provider": settings.image_provider,
    }
    return raw, dict.fromkeys(raw, "env")


def _row_values(row: LlmConfig) -> dict[str, object]:
    values: dict[str, object] = {}
    for name, column in TEXT_FIELDS.items():
        value = getattr(row, column)
        if value is not None:
            values[name] = value
    for name, column in INT_FIELDS.items():
        value = getattr(row, column)
        if value is not None:
            values[name] = value
    for name, column in SECRET_FIELDS.items():
        decrypted = crypto.decrypt_secret(getattr(row, column))
        if decrypted is not None:
            values[name] = decrypted
    return values


async def _layers(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[dict[str, object], dict[str, str], bool]:
    """逐层叠加，返回 (原始值, 各字段来源, 是否锁定 provider)。"""
    raw, origin = _env_raw()
    lock = False

    global_row = await session.scalar(select(LlmConfig).where(LlmConfig.scope == "global"))
    if global_row is not None:
        for name, value in _row_values(global_row).items():
            raw[name] = value
            origin[name] = "global"
        lock = global_row.lock_image_provider

    user_row = await session.scalar(
        select(LlmConfig).where(LlmConfig.scope == "user", LlmConfig.user_id == user_id)
    )
    if user_row is not None:
        values = _row_values(user_row)
        if lock:
            values.pop("image_provider", None)  # 强制锁：用户 provider 覆盖被忽略
        for name, value in values.items():
            raw[name] = value
            origin[name] = "user"

    return raw, origin, lock


def _finalize(raw: dict[str, object], lock: bool) -> ResolvedLlmConfig:
    """与改造前 llm.py / openai_images.py 一致的兜底链。"""
    settings = get_settings()
    planner_base = str(raw["planner_base_url"] or "") or (
        f"{settings.dashscope_base_url.rstrip('/')}{compatible_path()}"
    )
    planner_key = str(raw["planner_api_key"] or "") or settings.dashscope_api_key
    images_base = str(raw["images_base_url"] or "") or planner_base
    images_key = str(raw["images_api_key"] or "") or planner_key
    return ResolvedLlmConfig(
        planner_base_url=planner_base,
        planner_api_key=planner_key,
        planner_model=str(raw["planner_model"] or ""),
        planner_timeout=float(raw["planner_timeout"] or 60.0),
        planner_max_retries=int(raw["planner_max_retries"] or 2),
        images_base_url=images_base,
        images_api_key=images_key,
        images_model=str(raw["images_model"] or ""),
        images_sizes=str(raw["images_sizes"] or ""),
        image_provider=str(raw["image_provider"] or "mock"),
        lock_image_provider=lock,
    )


async def resolve(session: AsyncSession, user_id: uuid.UUID) -> ResolvedLlmConfig:
    cached = _cache.get(user_id)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1]

    raw, _, lock = await _layers(session, user_id)
    config = _finalize(raw, lock)
    _cache[user_id] = (time.monotonic(), config)
    return config


async def provider_for(session: AsyncSession, user_id: uuid.UUID):
    """工具与批量任务的取用入口：按任务归属用户解析配置再取 provider。"""
    from app.providers import get_image_provider

    return get_image_provider(await resolve(session, user_id))


# ---------------------------------------------------------------- 视图


async def effective_view(
    session: AsyncSession, user_id: uuid.UUID
) -> dict:
    """生效配置（key 打码）+ 各字段来源 + 用户覆盖了哪些字段。"""
    raw, origin, lock = await _layers(session, user_id)
    config = _finalize(raw, lock)

    overridden = sorted(
        name for name, source in origin.items() if source == "user"
    )
    return {
        "planner_base_url": config.planner_base_url,
        "planner_model": config.planner_model,
        "planner_timeout": config.planner_timeout,
        "planner_max_retries": config.planner_max_retries,
        "planner_api_key_masked": mask_secret(config.planner_api_key),
        "images_base_url": config.images_base_url,
        "images_model": config.images_model,
        "images_sizes": config.images_sizes,
        "images_api_key_masked": mask_secret(config.images_api_key),
        "image_provider": config.image_provider,
        "lock_image_provider": lock,
        "source": origin,
        "overridden": overridden,
    }


async def overrides_view(session: AsyncSession, user_id: uuid.UUID) -> dict:
    """用户自己设置的覆盖值（key 打码）。前端表单据此回填非密钥字段。"""
    row = await session.scalar(
        select(LlmConfig).where(LlmConfig.scope == "user", LlmConfig.user_id == user_id)
    )
    if row is None:
        return {"values": {}, "updated_at": None}
    values: dict[str, object] = {}
    for name, column in TEXT_FIELDS.items():
        value = getattr(row, column)
        if value is not None:
            values[name] = value
    for name, column in INT_FIELDS.items():
        value = getattr(row, column)
        if value is not None:
            values[name] = value
    for name, column in SECRET_FIELDS.items():
        if getattr(row, column) is not None:
            values[name] = "••••"  # 只写字段：不回明文，留空=不变
    return {"values": values, "updated_at": row.updated_at.isoformat() if row.updated_at else None}


# ---------------------------------------------------------------- 写入


async def _upsert(
    session: AsyncSession,
    *,
    scope: str,
    user_id: uuid.UUID | None,
    updates: dict[str, object],
    actor_id: uuid.UUID,
    action: str,
) -> list[str]:
    """updates: 字段名 → 新值（None = 清除覆盖）。返回变更的字段名列表。"""
    query = (
        select(LlmConfig).where(LlmConfig.scope == "global")
        if scope == "global"
        else select(LlmConfig).where(LlmConfig.scope == "user", LlmConfig.user_id == user_id)
    )
    row = await session.scalar(query)
    if row is None:
        row = LlmConfig(scope=scope, user_id=user_id)
        session.add(row)

    changed: list[str] = []
    diff: dict[str, object] = {}
    for name, value in updates.items():
        column = ALL_FIELDS[name]
        current = getattr(row, column)
        is_secret = name in SECRET_FIELDS
        if is_secret:
            if current is None and value is None:
                continue
            changed.append(name)
            diff[name] = "已清除" if value is None else "已变更"
        else:
            if current == value:
                continue
            changed.append(name)
            diff[name] = {"from": current, "to": value}
        setattr(row, column, value)

    if not changed:
        return []

    row.updated_by = actor_id

    session.add(
        LlmConfigAudit(
            actor_id=actor_id,
            scope=scope,
            target_user_id=user_id if scope == "user" else None,
            action=action,
            diff=diff,
        )
    )
    await session.commit()
    invalidate()
    logger.info(
        "LLM 配置已更新 scope=%s user_id=%s fields=%s", scope, user_id, changed
    )
    return changed


async def save_user_override(
    session: AsyncSession,
    user_id: uuid.UUID,
    updates: dict[str, object],
    *,
    lock_image_provider: bool | None = None,
) -> list[str]:
    """用户覆盖。lock 是全局行字段，用户提交的一律忽略（后端强制，不靠前端）。"""
    updates.pop("lock_image_provider", None)

    global_row = await session.scalar(select(LlmConfig).where(LlmConfig.scope == "global"))
    if "image_provider" in updates and global_row is not None and global_row.lock_image_provider:
        raise FieldLocked("管理员已锁定模型类型，不能自行切换 image_provider")

    # 用户级 base_url 是 SSRF 攻击面：保存与测试都要过同一道校验
    for name in ("planner_base_url", "images_base_url"):
        url = updates.get(name)
        if url:
            ensure_public_url(str(url))

    return await _upsert(
        session,
        scope="user",
        user_id=user_id,
        updates=updates,
        actor_id=user_id,
        action="update",
    )


async def save_global(
    session: AsyncSession,
    admin_id: uuid.UUID,
    updates: dict[str, object],
    *,
    lock_image_provider: bool | None = None,
) -> list[str]:
    saved = await _upsert(
        session,
        scope="global",
        user_id=None,
        updates=updates,
        actor_id=admin_id,
        action="update",
    )
    if lock_image_provider is not None:
        row = await session.scalar(select(LlmConfig).where(LlmConfig.scope == "global"))
        if row is not None and row.lock_image_provider != lock_image_provider:
            row.lock_image_provider = lock_image_provider
            session.add(
                LlmConfigAudit(
                    actor_id=admin_id,
                    scope="global",
                    action="update",
                    diff={"lock_image_provider": {"to": lock_image_provider}},
                )
            )
            await session.commit()
            invalidate()
            saved.append("lock_image_provider")
    return saved


async def clear_user_override(session: AsyncSession, user_id: uuid.UUID) -> bool:
    row = await session.scalar(
        select(LlmConfig).where(LlmConfig.scope == "user", LlmConfig.user_id == user_id)
    )
    if row is None:
        return False
    await session.delete(row)
    session.add(
        LlmConfigAudit(
            actor_id=user_id,
            scope="user",
            target_user_id=user_id,
            action="clear",
            diff={"cleared": True},
        )
    )
    await session.commit()
    invalidate(user_id)
    return True


async def audit_list(session: AsyncSession, limit: int = 100) -> list[LlmConfigAudit]:
    result = await session.scalars(
        select(LlmConfigAudit).order_by(LlmConfigAudit.created_at.desc()).limit(limit)
    )
    return list(result)


# ---------------------------------------------------------------- 测试连接


async def draft_config(
    session: AsyncSession,
    user_id: uuid.UUID,
    draft: dict[str, object] | None,
    *,
    as_global: bool = False,
) -> tuple[ResolvedLlmConfig, dict[str, str]]:
    """把未保存的草稿叠加在生效配置上，得到一个临时 ResolvedLlmConfig。

    admin 测全局时以「env → 全局行 → 草稿」合并；用户测试时以
    「env → 全局行 → 自己的行 → 草稿」合并。草稿密钥是明文。
    """
    raw, origin, lock = await _layers(session, user_id)
    if as_global:
        # 全局视角不应带上个人覆盖
        raw, origin = _env_raw()
        global_row = await session.scalar(select(LlmConfig).where(LlmConfig.scope == "global"))
        if global_row is not None:
            for name, value in _row_values(global_row).items():
                raw[name] = value
                origin[name] = "global"
    for name, value in (draft or {}).items():
        if value is not None and value != "":
            raw[name] = value
            origin[name] = "draft"
    return _finalize(raw, lock), origin


async def test_connection(
    session: AsyncSession,
    user_id: uuid.UUID,
    draft: dict[str, object] | None,
    *,
    as_global: bool = False,
    include_images: bool = True,
) -> dict:
    import httpx

    now = time.monotonic()
    if not as_global:
        last = _test_last.get(user_id)
        if last is not None and now - last < TEST_INTERVAL:
            from fastapi import HTTPException

            raise HTTPException(
                429, "测试太频繁，请稍后再试（每分钟一次）"
            )
        _test_last[user_id] = now

    config, _ = await draft_config(session, user_id, draft, as_global=as_global)
    session.add(
        LlmConfigAudit(
            actor_id=user_id,
            scope="global" if as_global else "user",
            target_user_id=None if as_global else user_id,
            action="test",
            diff={"fingerprint": config.fingerprint, "provider": config.image_provider},
        )
    )
    await session.commit()

    result: dict[str, object] = {"fingerprint": config.fingerprint}

    started = time.monotonic()
    if not config.planner_api_key:
        result["planner"] = {"ok": False, "error": "未配置规划模型 API Key"}
    else:
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                response = await client.post(
                    config.planner_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {config.planner_api_key}"},
                    json={
                        "model": config.planner_model,
                        "messages": [{"role": "user", "content": "连接测试"}],
                        "max_tokens": 16,
                    },
                )
            if response.status_code == 200:
                result["planner"] = {
                    "ok": True,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "model": config.planner_model,
                }
            else:
                result["planner"] = {
                    "ok": False,
                    "status": response.status_code,
                    "error": response.text[:200],
                }
        except httpx.HTTPError as exc:
            result["planner"] = {"ok": False, "error": str(exc)[:200]}

    images: dict[str, object]
    if not include_images:
        images = {"skipped": "未请求图像测试"}
    elif config.image_provider == "mock":
        images = {"skipped": "mock 不需要测试"}
    elif config.image_provider != "openai" or not (
        config.images_api_key and config.images_model
    ):
        images = {"skipped": "图像模型未配置完整"}
    else:
        from app.providers.openai_images import parse_sizes

        sizes = parse_sizes(config.images_sizes)
        size = f"{min(sizes, key=lambda s: s[0] * s[1])[0]}x{min(sizes, key=lambda s: s[0] * s[1])[1]}" if sizes else "1024x1024"
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
                response = await client.post(
                    config.images_base_url.rstrip("/") + "/images/generations",
                    headers={"Authorization": f"Bearer {config.images_api_key}"},
                    json={
                        "model": config.images_model,
                        "prompt": "连接测试：生成一张纯灰色背景图",
                        "n": 1,
                        "size": size,
                    },
                )
            if response.status_code == 200:
                images = {
                    "ok": True,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "model": config.images_model,
                    "size": size,
                }
            else:
                images = {"ok": False, "status": response.status_code, "error": response.text[:200]}
        except httpx.HTTPError as exc:
            images = {"ok": False, "error": str(exc)[:200]}
    result["images"] = images
    return result
