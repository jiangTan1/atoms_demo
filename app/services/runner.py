"""Runner 与 SessionService 的生命周期管理。

按 SESSION_BACKEND 配置创建 InMemorySessionService 或 SqliteSessionService，
并提供 Runner 单例的初始化与释放。
"""

from __future__ import annotations

from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService
from google.adk.sessions.sqlite_session_service import SqliteSessionService

from app.agent.root_agent import root_agent
from app.config import APP_NAME, PROJECT_ROOT, Settings

# 落在项目 data/ 下，避免依赖进程工作目录
SQLITE_DB_PATH = str(PROJECT_ROOT / "data" / "sessions.db")


def create_session_service(settings: Settings) -> BaseSessionService:
    """按配置返回会话后端；sqlite 时确保 data/ 目录存在。"""
    if settings.session_backend == "sqlite":
        (PROJECT_ROOT / "data").mkdir(exist_ok=True)
        return SqliteSessionService(db_path=SQLITE_DB_PATH)
    return InMemorySessionService()


class RunnerService:
    """把 Runner 与 SessionService 绑在一起，随应用启动创建、关闭释放。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session_service = create_session_service(settings)
        self.runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=self.session_service,
        )

    async def aclose(self) -> None:
        await self.runner.close()


async def create_session(
    session_service: BaseSessionService,
    *,
    user_id: str,
    session_id: str | None = None,
):
    """新建会话；session_id 为空时由 ADK 生成。"""
    return await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )


async def get_session(
    session_service: BaseSessionService,
    *,
    user_id: str,
    session_id: str,
):
    """读取会话，不存在时返回 None。"""
    return await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )


async def list_sessions(
    session_service: BaseSessionService,
    *,
    user_id: str,
    limit: int,
):
    """按最近更新时间倒序返回会话，最多 limit 个。

    list_sessions 返回的会话不含事件，标题与消息数需调用方再逐个 get_session 推导。
    """
    response = await session_service.list_sessions(app_name=APP_NAME, user_id=user_id)
    sessions = list(getattr(response, "sessions", None) or [])
    sessions.sort(key=lambda item: getattr(item, "last_update_time", 0) or 0, reverse=True)
    return sessions[:limit]