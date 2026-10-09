"""应用装配入口。

注册路由、管理 Runner 生命周期、托管前端构建产物（web/dist）。

前端源码位于 web/src，由 Vite 构建产出到 web/dist 并随仓库交付；服务只托管产物目录，
启动前校验产物入口文件是否存在，缺失时直接启动失败而不是运行期白屏（见 design.md 决策 7）。

uvicorn 入口：app.main:app
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth as auth_api
from app.api import chat as chat_api
from app.api import examples as examples_api
from app.api import preview as preview_api
from app.api import sessions as sessions_api
from app.api import shares as shares_api
from app.api import versions as versions_api
from app.api import workspace as workspace_api
from app.config import Settings, get_settings
from app.services.accounts import AccountService
from app.services.runner import RunnerService
from app.services.shares import ShareService

WEB_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"


def ensure_web_build() -> None:
    """启动前校验前端构建产物入口文件存在；缺失则启动失败并给出可修复的中文提示。

    宁可在这里明确失败，也不要在运行期以「页面空白」的方式暴露产物缺失。
    """
    entry = WEB_DIR / "index.html"
    if not entry.is_file():
        raise RuntimeError(
            f"前端构建产物缺失：未找到 {entry}。"
            "请先在 web/ 目录执行 `npm install && npm run build` 生成产物，"
            "或拉取仓库中最新的 web/dist/ 目录后再启动服务。"
        )


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
    # 前端产物缺失时在此直接抛出，使服务启动失败而不是提供空白页面
    ensure_web_build()

    app = FastAPI(title="代码辅助智能体", lifespan=lifespan)
    app.state.settings = get_settings()

    app.include_router(auth_api.router)
    app.include_router(sessions_api.router)
    app.include_router(chat_api.router)
    app.include_router(workspace_api.router)
    app.include_router(versions_api.router)
    app.include_router(shares_api.router)
    app.include_router(examples_api.router)
    # 预览与分享预览路由必须在静态资源挂载之前注册，否则会被 "/" 的挂载先吃掉
    app.include_router(preview_api.token_router)
    app.include_router(preview_api.router)
    app.include_router(shares_api.share_router)

    # 静态前端挂在最后，/api/* 与 /preview/*、/share/* 由上面的路由优先匹配
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()