"""应用装配入口。

注册路由、管理 Runner 生命周期、托管 web/ 静态前端。

uvicorn 入口：app.main:app
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import chat as chat_api
from app.api import sessions as sessions_api
from app.api import workspace as workspace_api
from app.config import Settings, get_settings
from app.services.runner import RunnerService

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时装配配置与 Runner，关闭时释放。配置缺失会在这里直接抛错。"""
    settings: Settings = app.state.settings
    service = RunnerService(settings)
    app.state.session_service = service.session_service
    app.state.runner = service.runner
    yield
    await service.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="代码辅助智能体", lifespan=lifespan)
    app.state.settings = get_settings()

    app.include_router(sessions_api.router)
    app.include_router(chat_api.router)
    app.include_router(workspace_api.router)

    # 静态前端挂在最后，/api/* 由上面的路由优先匹配
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()