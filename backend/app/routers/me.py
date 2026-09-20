"""个人 LLM 配置接口：查看生效配置、设置/清除覆盖、测试连接。

所有端点都要求登录；每个用户只能读写自己的覆盖行。
"""

from fastapi import APIRouter, HTTPException, status

from app.db import SessionDep
from app.deps import CurrentUser
from app.schemas.llm_config import LlmConfigIn, MeLlmConfigOut, OverridesView, TestOut
from app.services import crypto
from app.services import llm_config as config_service

router = APIRouter(prefix="/me", tags=["me"])


async def _view(session, user_id) -> MeLlmConfigOut:
    effective = await config_service.effective_view(session, user_id)
    overrides = await config_service.overrides_view(session, user_id)
    return MeLlmConfigOut(
        effective=effective, overrides=OverridesView.model_validate(overrides)
    )


def _updates_of(payload: LlmConfigIn) -> dict[str, object]:
    """请求体 → 列更新字典。语义：不传=不变；空串=清除覆盖；有值=设置。

    密钥加密在此完成，之后的链路见不到明文。
    """
    updates: dict[str, object] = {}
    for name in payload.model_fields_set:
        if name in ("lock_image_provider", "include_images"):
            continue
        value = getattr(payload, name)
        if name in config_service.SECRET_FIELDS:
            updates[name] = crypto.encrypt_secret(value) if value else None
        else:
            # 文本字段空串同样表示清除覆盖
            updates[name] = value if value not in ("", None) else None
    return updates


@router.get("/llm-config")
async def get_config(user: CurrentUser, session: SessionDep) -> MeLlmConfigOut:
    return await _view(session, user.id)


@router.put("/llm-config")
async def put_config(
    payload: LlmConfigIn, user: CurrentUser, session: SessionDep
) -> MeLlmConfigOut:
    updates = _updates_of(payload)
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有需要更新的字段")
    try:
        await config_service.save_user_override(session, user.id, updates)
    except config_service.FieldLocked as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    except config_service.UrlNotAllowed as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return await _view(session, user.id)


@router.delete("/llm-config", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(user: CurrentUser, session: SessionDep) -> None:
    await config_service.clear_user_override(session, user.id)


@router.post("/llm-config/test")
async def test_config(
    payload: LlmConfigIn, user: CurrentUser, session: SessionDep
) -> TestOut:
    draft = {}
    for name in payload.model_fields_set:
        if name in ("lock_image_provider", "include_images"):
            continue
        value = getattr(payload, name)
        if value not in (None, ""):
            draft[name] = value
    if payload.planner_base_url or payload.images_base_url:
        # 用户级 base_url 必须过 SSRF 校验（含未保存的草稿值）
        for url_field in ("planner_base_url", "images_base_url"):
            url = getattr(payload, url_field)
            if url:
                try:
                    config_service.ensure_public_url(url)
                except config_service.UrlNotAllowed as exc:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    result = await config_service.test_connection(
        session,
        user.id,
        draft,
        as_global=False,
        include_images=payload.include_images,
    )
    return TestOut.model_validate(result)
