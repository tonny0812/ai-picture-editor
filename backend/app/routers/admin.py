"""管理端接口。整个路由树的每个端点都必须挂 AdminUser 依赖。"""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.db import SessionDep
from app.deps import AdminUser
from app.schemas.admin import AdminUserOut, RolePatchIn
from app.schemas.llm_config import EffectiveView, LlmConfigIn, TestOut
from app.services import auth as auth_service
from app.services import llm_config as config_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    _: AdminUser,
    session: SessionDep,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[AdminUserOut]:
    users = await auth_service.list_users(session, limit=limit)
    return [AdminUserOut.model_validate(user) for user in users]


@router.patch("/users/{user_id}/role")
async def patch_role(
    user_id: uuid.UUID,
    payload: RolePatchIn,
    admin: AdminUser,
    session: SessionDep,
) -> AdminUserOut:
    # 禁止操作自己：否则最后一个管理员可能把自己降级，系统再无法进入配置页
    if user_id == admin.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "不能修改自己的角色，请由其他管理员操作"
        )
    target = await auth_service.get_by_id(session, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    await auth_service.set_role(session, target, payload.role)
    return AdminUserOut.model_validate(target)


# ---- 全局 LLM 配置 ----


@router.get("/llm-config")
async def get_llm_config(_: AdminUser, session: SessionDep) -> EffectiveView:
    """生效的全局配置视图（key 打码，source 标明 env / global）。"""
    view = await config_service.effective_view(session, uuid.UUID(int=0))
    # 用户级叠加层不存在（UUID(int=0) 不会命中任何用户行），source 里不会有 user
    return EffectiveView.model_validate(view)


@router.put("/llm-config")
async def put_llm_config(
    payload: LlmConfigIn, admin: AdminUser, session: SessionDep
) -> EffectiveView:
    updates: dict[str, object] = {}
    for name in payload.model_fields_set:
        if name in ("lock_image_provider", "include_images"):
            continue
        value = getattr(payload, name)
        if name in config_service.SECRET_FIELDS:
            updates[name] = crypto.encrypt_secret(value) if value else None
        else:
            updates[name] = value if value not in ("", None) else None
    if not updates and payload.lock_image_provider is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有需要更新的字段")
    # admin 配全局不做 SSRF 限制（管理员本就可控整个部署）
    await config_service.save_global(
        session,
        admin.id,
        updates,
        lock_image_provider=payload.lock_image_provider,
    )
    view = await config_service.effective_view(session, uuid.UUID(int=0))
    return EffectiveView.model_validate(view)


@router.post("/llm-config/test")
async def test_llm_config(
    payload: LlmConfigIn, admin: AdminUser, session: SessionDep
) -> TestOut:
    draft = {}
    for name in payload.model_fields_set:
        if name in ("lock_image_provider", "include_images"):
            continue
        value = getattr(payload, name)
        if value not in (None, ""):
            draft[name] = value
    result = await config_service.test_connection(
        session,
        admin.id,
        draft,
        as_global=True,
        include_images=payload.include_images,
    )
    return TestOut.model_validate(result)


@router.get("/llm-config/audit")
async def get_llm_config_audit(
    _: AdminUser,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    audits = await config_service.audit_list(session, limit=limit)
    return [
        {
            "id": str(item.id),
            "actor_id": str(item.actor_id) if item.actor_id else None,
            "scope": item.scope,
            "target_user_id": str(item.target_user_id) if item.target_user_id else None,
            "action": item.action,
            "diff": item.diff,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in audits
    ]
