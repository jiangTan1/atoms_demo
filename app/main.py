"""应用装配入口。

注册路由、管理 Runner 生命周期、托管 web/ 静态前端。

uvicorn 入口：app.main:app
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth as auth_api
from app.api import chat as chat_api
from app.api import preview as preview_api
from app.api import sessions as sessions_api
from app.api import shares as shares_api
from app.api import versions as versions_api
from app.api import workspace as workspace_api
from app.config import Settings, get_settings
from app.services.accounts import AccountService
from app.services.runner import RunnerService
from app.services.shares import ShareService

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时装配配置、账号服务与 Runner，关闭时释放。配置缺失会在这里直接抛错。"""
    settings: Settings = app.state.settings

    # 账号库独立于会话库，随应用启动初始化；库为空时用配置项 ADMIN_USERNAME /
    # ADMIN_PASSWORD 创建首个管理员，缺失则在此抛出 ConfigError 使启动失败
    accounts = AccountService()
    accounts.ensure_admin(settings.admin_username, settings.admin_password)
    app.state.accounts = accounts

    # 分享库同样独立，持久化不随 SESSION_BACKEND 变化
    app.state.shares = ShareService()

    service = RunnerService(settings)
    app.state.session_service = service.session_service
    app.state.runner = service.runner
    yield
    await service.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="代码辅助智能体", lifespan=lifespan)
    app.state.settings = get_settings()

    app.include_router(auth_api.router)
    app.include_router(sessions_api.router)
    app.include_router(chat_api.router)
    app.include_router(workspace_api.router)
    app.include_router(versions_api.router)
    app.include_router(shares_api.router)
    # 预览与分享预览路由必须在静态资源挂载之前注册，否则会被 "/" 的挂载先吃掉
    app.include_router(preview_api.token_router)
    app.include_router(preview_api.router)
    app.include_router(shares_api.share_router)

    # 静态前端挂在最后，/api/* 与 /preview/*、/share/* 由上面的路由优先匹配
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()