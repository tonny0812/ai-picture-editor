import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import storage
from app.config import get_settings
from app.queue import close_queue
from app.routers import admin, assets, auth, batches, events, health, me, prompts, runs, sessions

settings = get_settings()


class SPAStaticFiles(StaticFiles):
    """前端产物托管。

    前端使用 BrowserRouter 的真实路径（/editor/:id 等），刷新或直接访问深链时
    StaticFiles 默认返回 404。这里在静态资源缺失时回落到 index.html，
    交由前端路由接管；/api 与 /events 前缀仍保持 404，避免把接口 404 伪装成页面。
    """

    BACKEND_PREFIXES = ("api/", "events/")

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or path.startswith(self.BACKEND_PREFIXES):
                raise
            return await super().get_response("index.html", scope)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(storage.ensure_bucket)
    yield
    await close_queue()


app = FastAPI(
    title="AI 修图智能体",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

api = APIRouter(prefix="/api")
api.include_router(health.router)
api.include_router(auth.router)
api.include_router(me.router)
api.include_router(assets.router)
api.include_router(runs.router)
api.include_router(sessions.router)
api.include_router(prompts.router)
api.include_router(batches.router)
api.include_router(admin.router)
app.include_router(api)

# SSE 不挂在 /api 下，便于反向代理单独关闭缓冲
app.include_router(events.router)

# 生产环境下前端与 API 同源，静态产物由本服务托管；开发环境走 Vite dev proxy。
if settings.frontend_dist.is_dir():
    app.mount(
        "/", SPAStaticFiles(directory=settings.frontend_dist, html=True), name="frontend"
    )
