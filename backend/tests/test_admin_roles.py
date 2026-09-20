"""角色体系与管理员闸门的权限矩阵测试（对应 docs/LLM-CONFIG-DESIGN.md §2.3）。"""

import uuid

import httpx
import pytest

from app import cli
from app.config import get_settings
from app.db import SessionFactory
from app.models import Role
from app.services import auth as auth_service

USERS_ENDPOINT = "/api/admin/users"


async def _register(client: httpx.AsyncClient, credentials: dict[str, str]) -> dict:
    response = await client.post("/api/auth/register", json=credentials)
    assert response.status_code == 201, response.text
    return response.json()


async def _load(username: str):
    async with SessionFactory() as session:
        user = await auth_service.get_by_username(session, username)
        assert user is not None, f"用户不存在：{username}"
        return user


async def _me(client: httpx.AsyncClient) -> dict:
    response = await client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    return response.json()


# ---- 注册与角色来源 ----


async def test_register_defaults_to_normal_user(client, credentials):
    body = await _register(client, credentials)

    assert body["role"] == "user"
    assert (await _me(client))["role"] == "user"


async def test_whitelisted_username_registers_as_admin(admin_client, credentials):
    me = await _me(admin_client)

    assert me["username"] == credentials["username"]
    assert me["role"] == "admin"


async def test_whitelist_matching_is_exact(client, credentials):
    """白名单是精确匹配：大小写与空白都不算命中。"""
    settings = get_settings()
    original, settings.admin_usernames = (
        settings.admin_usernames,
        f" {credentials['username'].upper()} ",
    )

    try:
        body = await _register(client, credentials)
    finally:
        settings.admin_usernames = original

    assert body["role"] == "user"


# ---- 管理员闸门（每格越权都验一次）----


async def test_admin_endpoints_reject_anonymous(client):
    assert (await client.get(USERS_ENDPOINT)).status_code == 401


async def test_normal_user_cannot_list_users(client, credentials):
    await _register(client, credentials)

    assert (await client.get(USERS_ENDPOINT)).status_code == 403


async def test_normal_user_cannot_change_any_role(client, credentials):
    await _register(client, credentials)

    response = await client.patch(f"{USERS_ENDPOINT}/{uuid.uuid4()}/role", json={"role": "admin"})

    assert response.status_code == 403


async def test_admin_can_list_users_with_roles(admin_client, second_client, other_credentials):
    await _register(second_client, other_credentials)

    response = await admin_client.get(USERS_ENDPOINT, params={"limit": 500})

    assert response.status_code == 200
    roles = {row["username"]: row["role"] for row in response.json()}
    assert roles[other_credentials["username"]] == "user"


# ---- 角色变更 ----


async def test_admin_promotes_other_user_who_then_gains_access(
    admin_client, second_client, other_credentials
):
    await _register(second_client, other_credentials)
    target = await _load(other_credentials["username"])

    response = await admin_client.patch(
        f"{USERS_ENDPOINT}/{target.id}/role", json={"role": "admin"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert (await _me(second_client))["role"] == "admin"
    assert (await second_client.get(USERS_ENDPOINT)).status_code == 200


async def test_admin_demotes_other_user_who_then_loses_access(
    admin_client, second_client, other_credentials
):
    await _register(second_client, other_credentials)
    target = await _load(other_credentials["username"])
    await admin_client.patch(f"{USERS_ENDPOINT}/{target.id}/role", json={"role": "admin"})
    assert (await second_client.get(USERS_ENDPOINT)).status_code == 200

    response = await admin_client.patch(
        f"{USERS_ENDPOINT}/{target.id}/role", json={"role": "user"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "user"
    assert (await second_client.get(USERS_ENDPOINT)).status_code == 403


async def test_admin_cannot_change_own_role(admin_client, credentials):
    own = await _load(credentials["username"])

    response = await admin_client.patch(f"{USERS_ENDPOINT}/{own.id}/role", json={"role": "user"})

    assert response.status_code == 400
    assert (await _load(credentials["username"])).role == Role.ADMIN
    assert (await admin_client.get(USERS_ENDPOINT)).status_code == 200


async def test_role_patch_rejects_unknown_role_value(admin_client, credentials):
    own = await _load(credentials["username"])

    response = await admin_client.patch(f"{USERS_ENDPOINT}/{own.id}/role", json={"role": "root"})

    assert response.status_code == 422


async def test_role_patch_returns_404_for_unknown_user(admin_client):
    response = await admin_client.patch(
        f"{USERS_ENDPOINT}/{uuid.uuid4()}/role", json={"role": "user"}
    )

    assert response.status_code == 404


# ---- CLI 引导通道 ----


async def test_promote_command_takes_effect_without_relogin(client, credentials):
    await _register(client, credentials)

    assert await cli.run(["promote", credentials["username"]]) == cli.EXIT_OK

    # 角色每请求从库里读，故旧 cookie 立即生效，不需要重新登录
    assert (await _me(client))["role"] == "admin"
    assert (await client.get(USERS_ENDPOINT)).status_code == 200


async def test_promote_command_reports_unknown_user(capsys):
    exit_code = await cli.run(["promote", "test_nobody_here"])

    assert exit_code == cli.EXIT_FAILED
    assert "用户不存在" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("role", "admin_count", "expected"),
    [
        (Role.ADMIN, 1, False),
        (Role.ADMIN, 2, True),
        (Role.USER, 1, True),
        (Role.USER, 0, True),
    ],
)
def test_can_demote_protects_the_sole_admin(role, admin_count, expected):
    """唯一管理员降级后系统再没有管理入口，必须拦住。"""
    assert cli.can_demote(role, admin_count) is expected
