"""提示词模板渲染（纯函数）与提示词库 API 的测试。"""

import pytest
from sqlalchemy import delete

from app.db import SessionFactory
from app.models.prompt import PromptEntry, PromptTemplate
from app.prompts import (
    MissingVariable,
    defaults_of,
    extract_variables,
    render_template,
    strip_variables,
    tidy,
)

ENTRIES = "/api/prompts/entries"
TEMPLATES = "/api/prompts/templates"


@pytest.fixture
async def signed_in(client, credentials):
    await client.post("/api/auth/register", json=credentials)
    return client


@pytest.fixture
async def other_user(second_client, other_credentials):
    await second_client.post("/api/auth/register", json=other_credentials)
    return second_client


@pytest.fixture(autouse=True)
async def clean_prompts():
    """这两张表目前只由本文件写，跑完清空，避免用例之间互相污染。"""
    yield
    async with SessionFactory() as session:
        await session.execute(delete(PromptEntry))
        await session.execute(delete(PromptTemplate))
        await session.commit()


async def _builtin_template(**overrides) -> PromptTemplate:
    """插一条内置模板（user_id 为 NULL，接口层无法直接创建）。"""
    data = {
        "title": "内置·人物肖像",
        "category": "portrait",
        "description": "通用人像底稿",
        "prompt_template": "{{subject}}，{{light:柔和侧光}}，高清肖像",
        "negative_template": "低清，畸变",
        "variables": [{"name": "subject", "label": "主体", "placeholder": "一位…", "default": ""}],
        "default_ratio": "9:16",
        "default_count": 2,
    } | overrides
    async with SessionFactory() as session:
        template = PromptTemplate(user_id=None, **data)
        session.add(template)
        await session.commit()
        await session.refresh(template)
        return template


# ------------------------------------------------------------------ 渲染纯函数


def test_render_uses_default_when_value_missing():
    rendered = render_template("{{subject}}，{{light:柔和侧光}}", {"subject": "少女"})
    assert rendered == "少女，柔和侧光"


def test_render_raises_when_required_variable_missing():
    with pytest.raises(MissingVariable) as caught:
        render_template("{{subject}}，{{light}}", {"subject": "少女"})
    assert "light" in str(caught.value)


def test_extract_variables_keeps_order_without_duplicates():
    template = "{{a}}，{{b:1}}，{{a}}"
    assert extract_variables(template) == ["a", "b"]
    assert defaults_of(template) == {"b": "1"}


def test_render_tidies_leftover_punctuation():
    """变量留空会留下孤立逗号，不能原样丢给网关。"""
    assert render_template("{{a}}，{{b:}}，高清", {"a": "猫"}) == "猫，高清"
    assert tidy("猫，，，高清") == "猫，高清"
    assert tidy("，高清") == "高清"


def test_strip_variables_leaves_plain_text():
    assert strip_variables("{{a}}，{{b:x}}，高清") == "高清"


def test_render_handles_template_without_variables():
    assert render_template("一只橘猫", {}) == "一只橘猫"


# ------------------------------------------------------------------ 收藏 CRUD


async def test_entries_require_login(client):
    assert (await client.get(ENTRIES)).status_code == 401


async def test_create_then_list_entry(signed_in):
    created = await signed_in.post(
        ENTRIES, json={"title": "咖啡海报", "prompt": "一杯咖啡", "tags": ["饮品", "饮品"]}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "咖啡海报"
    assert body["tags"] == ["饮品"]  # 去重
    assert body["use_count"] == 0

    listed = (await signed_in.get(ENTRIES)).json()
    assert [item["title"] for item in listed] == ["咖啡海报"]


async def test_entries_can_be_filtered_by_category_tag_and_keyword(signed_in):
    await signed_in.post(
        ENTRIES,
        json={
            "title": "古镇夜景",
            "prompt": "青石板路",
            "category": "illustration",
            "tags": ["夜"],
        },
    )
    await signed_in.post(
        ENTRIES, json={"title": "牛奶盒子", "prompt": "白色纸盒", "category": "product"}
    )

    assert len((await signed_in.get(ENTRIES, params={"category": "product"})).json()) == 1
    assert len((await signed_in.get(ENTRIES, params={"tag": "夜"})).json()) == 1
    assert len((await signed_in.get(ENTRIES, params={"q": "纸盒"})).json()) == 1
    assert len((await signed_in.get(ENTRIES, params={"q": "不存在的关键词"})).json()) == 0


async def test_update_and_delete_entry(signed_in):
    body = (await signed_in.post(ENTRIES, json={"title": "初稿", "prompt": "一只猫"})).json()
    entry_id = body["id"]

    patched = await signed_in.patch(f"{ENTRIES}/{entry_id}", json={"title": "定稿", "tags": ["猫"]})
    assert patched.json()["title"] == "定稿"
    assert patched.json()["prompt"] == "一只猫"  # 未提交的字段保持原值

    assert (await signed_in.delete(f"{ENTRIES}/{entry_id}")).status_code == 204
    assert (await signed_in.get(f"{ENTRIES}/{entry_id}")).status_code == 404


async def test_other_users_entry_is_invisible(signed_in, other_user):
    body = (await signed_in.post(ENTRIES, json={"title": "私藏", "prompt": "秘密配方"})).json()

    assert (await other_user.get(f"{ENTRIES}/{body['id']}")).status_code == 404
    assert (await other_user.get(ENTRIES)).json() == []
    patch = await other_user.patch(f"{ENTRIES}/{body['id']}", json={"title": "改名"})
    assert patch.status_code == 404
    assert (await other_user.delete(f"{ENTRIES}/{body['id']}")).status_code == 404


async def test_use_increments_counter(signed_in):
    body = (await signed_in.post(ENTRIES, json={"title": "常用", "prompt": "一只猫"})).json()
    used = (await signed_in.post(f"{ENTRIES}/{body['id']}/use")).json()

    assert used["use_count"] == 1
    assert used["last_used_at"]


# ------------------------------------------------------------------ 模板


async def test_builtin_templates_are_visible(signed_in):
    await _builtin_template()
    listed = (await signed_in.get(TEMPLATES)).json()

    assert len(listed) == 1
    assert listed[0]["is_builtin"] is True
    assert listed[0]["variables"][0]["name"] == "subject"


async def test_builtin_template_is_read_only(signed_in):
    template = await _builtin_template()

    patch = await signed_in.patch(f"{TEMPLATES}/{template.id}", json={"title": "改了"})
    assert patch.status_code == 403

    delete = await signed_in.delete(f"{TEMPLATES}/{template.id}")
    assert delete.status_code == 403


async def test_render_reports_missing_variables_clearly(signed_in):
    template = await _builtin_template()

    missing = await signed_in.post(f"{TEMPLATES}/{template.id}/render", json={"values": {}})
    assert missing.status_code == 422
    assert "subject" in missing.json()["detail"]

    ok = await signed_in.post(
        f"{TEMPLATES}/{template.id}/render", json={"values": {"subject": "穿白裙的少女"}}
    )
    assert ok.status_code == 200
    assert ok.json()["prompt"] == "穿白裙的少女，柔和侧光，高清肖像"
    assert ok.json()["negative_prompt"] == "低清，畸变"


async def test_own_template_can_be_created_updated_and_removed(signed_in):
    created = await signed_in.post(
        TEMPLATES,
        json={
            "title": "我的架构图模板",
            "category": "architecture",
            "prompt_template": "{{system}} 的架构图，{{style:扁平矢量}}",
            "variables": [{"name": "system", "label": "系统名"}],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["is_builtin"] is False

    patched = await signed_in.patch(
        f"{TEMPLATES}/{body['id']}", json={"default_ratio": "16:9", "default_count": 2}
    )
    assert patched.json()["default_ratio"] == "16:9"

    assert (await signed_in.delete(f"{TEMPLATES}/{body['id']}")).status_code == 204
    assert (await signed_in.get(f"{TEMPLATES}/{body['id']}")).status_code == 404


async def test_other_users_template_is_invisible(signed_in, other_user):
    body = (
        await signed_in.post(TEMPLATES, json={"title": "我的模板", "prompt_template": "{{a}}"})
    ).json()

    assert (await other_user.get(f"{TEMPLATES}/{body['id']}")).status_code == 404
    # 别人的自建模板不该出现在列表里（列表里可能有内置模板，那是公共的）
    visible = [item["id"] for item in (await other_user.get(TEMPLATES)).json()]
    assert body["id"] not in visible


async def test_templates_can_be_filtered_by_category(signed_in):
    await _builtin_template()
    await signed_in.post(
        TEMPLATES, json={"title": "海报模板", "category": "poster", "prompt_template": "x"}
    )

    posters = (await signed_in.get(TEMPLATES, params={"category": "poster"})).json()
    assert [item["title"] for item in posters] == ["海报模板"]
