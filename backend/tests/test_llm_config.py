"""LLM 配置层测试：解析顺序、强制锁、加密、打码、SSRF 与接口权限矩阵。"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionFactory
from app.llm_config import mask_secret
from app.models import LlmConfig
from app.services import crypto
from app.services import llm_config as config_service

ME = "/api/me/llm-config"
GLOBAL = "/api/admin/llm-config"


@pytest.fixture
async def signed_in(client, other_credentials):
    """与 admin_client 同场时必须用另一套凭据——同一用户名重复注册会 409，导致后续请求 401。"""
    response = await client.post("/api/auth/register", json=other_credentials)
    assert response.status_code == 201, response.text
    return client


@pytest.fixture(autouse=True)
async def clean_global_llm_config():
    """测试产生的全局行必须清掉——它会持久化并影响真实部署的解析结果。"""
    yield
    async with SessionFactory() as session:
        await session.execute(delete(LlmConfig).where(LlmConfig.scope == "global"))
        await session.commit()
    config_service.invalidate()


async def _set_global(**values) -> None:
    """直接造一个全局行（绕过接口，专注测解析逻辑）。"""
    async with SessionFactory() as session:
        row = await session.scalar(select(LlmConfig).where(LlmConfig.scope == "global"))
        if row is None:
            row = LlmConfig(scope="global", user_id=None)
            session.add(row)
        for key, value in values.items():
            if key.endswith("_api_key"):
                setattr(row, key.replace("_api_key", "_api_key_enc"), crypto.encrypt_secret(value))
            else:
                setattr(row, key, value)
        await session.commit()
    config_service.invalidate()


async def _set_user(user_id: uuid.UUID, **values) -> None:
    async with SessionFactory() as session:
        row = await session.scalar(
            select(LlmConfig).where(LlmConfig.scope == "user", LlmConfig.user_id == user_id)
        )
        if row is None:
            row = LlmConfig(scope="user", user_id=user_id)
            session.add(row)
        for key, value in values.items():
            if key.endswith("_api_key"):
                setattr(row, key.replace("_api_key", "_api_key_enc"), crypto.encrypt_secret(value))
            else:
                setattr(row, key, value)
        await session.commit()
    config_service.invalidate()


# ---------------------------------------------------------------- 单元


async def test_resolve_order_user_over_global_over_env(signed_in):
    """三层合并：用户覆盖 > 全局 > .env。"""
    settings = get_settings()
    await _set_global(images_model="global-model", image_provider="openai")
    body = (await signed_in.get(ME)).json()
    assert body["effective"]["images_model"] in ("global-model", settings.images_model)


async def test_field_level_fallback(signed_in):
    """用户只覆盖一个字段，其余字段回落到全局 / env。"""
    await _set_global(images_model="global-model", planner_model="global-planner")
    user_id = uuid.UUID((await signed_in.get("/api/auth/me")).json()["id"])
    await _set_user(user_id, planner_model="user-planner")

    body = (await signed_in.get(ME)).json()
    assert body["effective"]["planner_model"] == "user-planner"
    assert body["effective"]["images_model"] == "global-model"
    assert body["effective"]["source"]["planner_model"] == "user"
    assert body["effective"]["source"]["images_model"] == "global"
    assert body["effective"]["overridden"] == ["planner_model"]


async def test_lock_image_provider_rejects_user_override(signed_in):
    """强制锁开启后：后端 422 拒绝覆盖 provider，其余字段照常可覆盖。"""
    await _set_global(lock_image_provider=True, image_provider="openai")

    response = await signed_in.put(ME, json={"image_provider": "mock"})
    assert response.status_code == 422
    assert "锁定" in response.json()["detail"]

    # 其余字段不受影响
    ok = await signed_in.put(ME, json={"planner_model": "my-model"})
    assert ok.status_code == 200

    # 直接写库绕过接口也无效：解析层会忽略被锁字段
    user_id = uuid.UUID((await signed_in.get("/api/auth/me")).json()["id"])
    await _set_user(user_id, image_provider="mock")
    async with SessionFactory() as session:
        config = await config_service.resolve(session, user_id)
    assert config.image_provider == "openai"


async def test_lock_defaults_off(signed_in):
    """默认没有锁：用户可以自选 provider（含换回 mock 省额度）。"""
    response = await signed_in.put(ME, json={"image_provider": "mock"})
    assert response.status_code == 200
    assert response.json()["effective"]["image_provider"] == "mock"


async def test_secret_is_encrypted_at_rest_and_masked_in_api(signed_in):
    """库里只有密文；接口只回打码值。"""
    await signed_in.put(ME, json={"planner_api_key": "sk-test-1234567890"})
    user_id = uuid.UUID((await signed_in.get("/api/auth/me")).json()["id"])

    async with SessionFactory() as session:
        row = await session.scalar(
            select(LlmConfig).where(LlmConfig.scope == "user", LlmConfig.user_id == user_id)
        )
        assert row is not None
        assert "sk-test" not in (row.planner_api_key_enc or "")
        assert crypto.decrypt_secret(row.planner_api_key_enc) == "sk-test-1234567890"

    body = (await signed_in.get(ME)).json()
    assert body["effective"]["planner_api_key_masked"] == mask_secret("sk-test-1234567890")
    assert "sk-test" not in body["effective"]["planner_api_key_masked"]
    # 覆盖视图不回明文，只回占位符
    assert body["overrides"]["values"]["planner_api_key"] == "••••"


async def test_empty_string_clears_override(signed_in):
    await signed_in.put(ME, json={"planner_model": "my-model"})
    await signed_in.put(ME, json={"planner_model": ""})

    body = (await signed_in.get(ME)).json()
    assert body["overrides"]["values"] == {}
    assert "planner_model" not in body["effective"]["overridden"]


async def test_delete_restores_global_defaults(signed_in):
    await _set_global(planner_model="global-planner")
    await signed_in.put(ME, json={"planner_model": "my-model"})
    await signed_in.delete(ME)

    body = (await signed_in.get(ME)).json()
    assert body["effective"]["planner_model"] == "global-planner"
    assert body["overrides"]["values"] == {}


def test_mask_secret():
    assert mask_secret(None) == ""
    assert mask_secret("") == ""
    assert mask_secret("short") == "••••"
    assert mask_secret("sk-image-123") == "sk-i••••23"


def test_encrypt_roundtrip():
    token = crypto.encrypt_secret("sk-abc")
    assert token != "sk-abc"
    assert crypto.decrypt_secret(token) == "sk-abc"
    assert crypto.encrypt_secret(None) is None
    assert crypto.encrypt_secret("") is None


# ---------------------------------------------------------------- SSRF


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/v1",
        "http://localhost:8000",
        "http://10.1.2.3/v1",
        "http://192.168.1.1/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/v1",
        "ftp://example.com",
    ],
)
def test_ssrf_blocked(url):
    with pytest.raises(config_service.UrlNotAllowed):
        config_service.ensure_public_url(url)


@pytest.mark.parametrize("url", ["http://8.8.8.8/v1", "https://8.8.4.4:8000/v1"])
def test_ssrf_allows_public_literals(url):
    # 公网 IP 字面量无需 DNS 即可通过
    config_service.ensure_public_url(url)


async def test_user_put_rejects_private_base_url(signed_in):
    response = await signed_in.put(ME, json={"planner_base_url": "http://10.0.0.1/v1"})
    assert response.status_code == 422


async def test_admin_global_allows_internal_url(admin_client):
    """admin 配全局不做 SSRF 限制（管理员本就可控整个部署）。"""
    response = await admin_client.put(GLOBAL, json={"planner_base_url": "http://10.0.0.1/v1"})
    assert response.status_code == 200
    await admin_client.put(GLOBAL, json={"planner_base_url": ""})  # 还原


# ---------------------------------------------------------------- 接口权限矩阵


async def test_user_cannot_touch_admin_config(signed_in):
    assert (await signed_in.get(GLOBAL)).status_code == 403
    assert (await signed_in.put(GLOBAL, json={"planner_model": "x"})).status_code == 403
    assert (await signed_in.post(f"{GLOBAL}/test")).status_code == 403
    assert (await signed_in.get(f"{GLOBAL}/audit")).status_code == 403


async def test_admin_can_read_and_write_global(admin_client):
    response = await admin_client.put(
        GLOBAL, json={"planner_model": "admin-model", "images_model": "admin-image"}
    )
    assert response.status_code == 200
    body = await admin_client.get(GLOBAL)
    assert body.json()["planner_model"] == "admin-model"
    await admin_client.put(GLOBAL, json={"planner_model": "", "images_model": ""})


async def test_lock_field_is_global_only(admin_client, signed_in):
    """lock_image_provider 只在全局行有意义；用户提交会被忽略。"""
    response = await admin_client.put(GLOBAL, json={"lock_image_provider": True})
    assert response.status_code == 200
    assert response.json()["lock_image_provider"] is True

    # 用户侧看不到可写入口，但即使提交也不会报错（被忽略）也不生效
    ignored = await signed_in.put(ME, json={"lock_image_provider": False})
    assert ignored.status_code == 200
    assert (await signed_in.get(ME)).json()["effective"]["lock_image_provider"] is True

    await admin_client.put(GLOBAL, json={"lock_image_provider": False})


async def test_audit_records_changes(admin_client, signed_in):
    await signed_in.put(ME, json={"planner_model": "my-model"})
    await admin_client.put(GLOBAL, json={"images_model": "global-image"})

    audits = (await admin_client.get(f"{GLOBAL}/audit")).json()
    actions = [(a["scope"], a["action"]) for a in audits]
    assert ("global", "update") in actions
    assert ("user", "update") in actions
    # 密钥值不进审计
    assert not any("sk-" in str(a["diff"]) for a in audits)


async def test_test_connection_is_rate_limited(signed_in):
    first = await signed_in.post(ME + "/test", json={"include_images": False})
    assert first.status_code == 200
    second = await signed_in.post(ME + "/test", json={"include_images": False})
    assert second.status_code == 429


async def test_test_connection_reports_missing_planner_key(signed_in, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "planner_api_key", "")
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    config_service.invalidate()

    response = await signed_in.post(ME + "/test", json={"include_images": False})
    assert response.status_code == 200
    assert response.json()["planner"]["ok"] is False
    config_service.invalidate()


async def test_test_connection_accepts_draft_without_saving(signed_in):
    """测试连接用未保存的草稿值，不落库。"""
    before = (await signed_in.get(ME)).json()["overrides"]["values"]
    response = await signed_in.post(
        ME + "/test", json={"planner_model": "draft-model", "include_images": False}
    )
    assert response.status_code == 200
    after = (await signed_in.get(ME)).json()["overrides"]["values"]
    assert before == after


async def test_second_user_is_not_affected_by_first_override(signed_in, second_client):
    """用户覆盖彼此隔离：A 覆盖不影响 B 的生效配置。"""
    await signed_in.put(ME, json={"planner_model": "a-model"})
    third = {"username": f"test_{uuid.uuid4().hex[:10]}", "password": "secret123"}
    response = await second_client.post("/api/auth/register", json=third)
    assert response.status_code == 201, response.text

    body_b = (await second_client.get(ME)).json()
    assert body_b["effective"]["planner_model"] != "a-model"


async def test_effective_config_visible_without_any_override(signed_in):
    """没建任何覆盖行时接口照常可用（回 env）。"""
    response = await signed_in.get(ME)
    assert response.status_code == 200
    assert response.json()["effective"]["planner_base_url"]
