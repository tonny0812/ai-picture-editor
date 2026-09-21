"""运维命令行。容器内执行：

    python -m app.cli promote <用户名>       # 提升为管理员
    python -m app.cli demote <用户名>        # 降回普通用户
    python -m app.cli list                  # 列出全部用户与角色
    python -m app.cli seed-prompts          # 写入/更新内置提示词模板（幂等）

页面注册无法自证身份，管理员引导只走这里（或 .env 的 ADMIN_USERNAMES 白名单）。
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.db import SessionFactory
from app.models import Role
from app.models.prompt import PromptTemplate
from app.seeds.prompt_templates import SEEDS
from app.services import auth as auth_service

EXIT_OK = 0
EXIT_FAILED = 1


def can_demote(role: Role, admin_count: int) -> bool:
    """唯一的管理员不允许降级——否则系统再没有进入配置页的入口。"""
    return not (role == Role.ADMIN and admin_count <= 1)


async def _set_role(username: str, role: Role) -> int:
    async with SessionFactory() as session:
        user = await auth_service.get_by_username(session, username)
        if user is None:
            print(f"用户不存在：{username}", file=sys.stderr)
            return EXIT_FAILED
        if user.role == role:
            print(f"{username} 已经是 {role.value}，无需修改")
            return EXIT_OK
        if not can_demote(user.role, await auth_service.count_admins(session)):
            print(f"{username} 是唯一的管理员，降级后将无人可管理配置", file=sys.stderr)
            return EXIT_FAILED

        await auth_service.set_role(session, user, role)
        print(f"已将 {username} 的角色改为 {role.value}")
        return EXIT_OK


async def _seed_prompts() -> int:
    """写入内置提示词模板。按标题 upsert：改了种子重跑一次即可同步。"""
    added = updated = 0
    async with SessionFactory() as session:
        for seed in SEEDS:
            row = await session.execute(
                select(PromptTemplate).where(
                    PromptTemplate.user_id.is_(None), PromptTemplate.title == seed["title"]
                )
            )
            template = row.scalar_one_or_none()
            if template is None:
                session.add(PromptTemplate(user_id=None, **seed))
                added += 1
            else:
                for key, value in seed.items():
                    setattr(template, key, value)
                updated += 1
        await session.commit()

    print(f"内置提示词模板：新增 {added} 个，更新 {updated} 个，共 {len(SEEDS)} 个")
    return EXIT_OK


async def _list_users() -> int:
    async with SessionFactory() as session:
        users = await auth_service.list_users(session)

    if not users:
        print("暂无用户")
        return EXIT_OK

    width = max(len(user.username) for user in users)
    for user in users:
        print(f"{user.username:<{width}}  {user.role.value:<6}  {user.id}")
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="AI 修图智能体运维命令")
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("promote", "把用户提升为管理员"),
        ("demote", "把管理员降回普通用户"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("username", help="已注册的用户名")
    commands.add_parser("list", help="列出全部用户及其角色")
    commands.add_parser("seed-prompts", help="写入内置提示词模板（幂等，改了模板重跑即可）")
    return parser


async def run(argv: list[str]) -> int:
    """异步入口，便于测试直接 await，无需额外开事件循环。"""
    args = _parser().parse_args(argv)
    if args.command == "promote":
        return await _set_role(args.username, Role.ADMIN)
    if args.command == "demote":
        return await _set_role(args.username, Role.USER)
    if args.command == "seed-prompts":
        return await _seed_prompts()
    return await _list_users()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
