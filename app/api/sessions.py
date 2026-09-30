"""会话接口。

提供会话新建、历史会话列表与历史消息读取，返回可供后续对话复用的 session_id。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.schemas import (
    DEFAULT_USER_ID,
    HistoryMessage,
    SessionCreateRequest,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
    SessionSummary,
)
from app.services.chat import events_to_messages
from app.services.runner import create_session, get_session, list_sessions

router = APIRouter(prefix="/api", tags=["sessions"])

# 历史列表为逐会话读取，用条数上限把开销封顶（见 design.md 决策 3）
HISTORY_LIMIT = 50
TITLE_MAX_LEN = 30
EMPTY_SESSION_TITLE = "（空会话）"


def _title_from(messages: list[dict]) -> str:
    """标题取首条使用者消息的摘要；没有使用者消息时标记为空会话。"""
    for message in messages:
        if message["role"] != "user":
            continue
        text = " ".join(message["text"].split())
        return text[:TITLE_MAX_LEN] + ("…" if len(text) > TITLE_MAX_LEN else "")
    return EMPTY_SESSION_TITLE


@router.post("/sessions", response_model=SessionResponse)
async def new_session(request: Request, payload: SessionCreateRequest | None = None) -> SessionResponse:
    """新建会话，返回的 session_id 可直接在 POST /api/chat 中复用。"""
    user_id = payload.user_id if payload else DEFAULT_USER_ID
    session = await create_session(request.app.state.session_service, user_id=user_id)
    return SessionResponse(session_id=session.id, user_id=user_id)


@router.get("/sessions", response_model=SessionListResponse)
async def read_sessions(
    request: Request,
    user_id: str = DEFAULT_USER_ID,
) -> SessionListResponse:
    """历史会话列表，按最近更新时间倒序返回。"""
    service = request.app.state.session_service
    sessions = await list_sessions(service, user_id=user_id, limit=HISTORY_LIMIT)

    summaries: list[SessionSummary] = []
    for item in sessions:
        detail = await get_session(service, user_id=user_id, session_id=item.id)
        messages = events_to_messages(detail) if detail is not None else []
        summaries.append(
            SessionSummary(
                session_id=item.id,
                title=_title_from(messages),
                updated_at=float(getattr(item, "last_update_time", 0) or 0),
                message_count=len(messages),
            )
        )
    return SessionListResponse(sessions=summaries)


@router.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def read_session_messages(
    session_id: str,
    request: Request,
    user_id: str = DEFAULT_USER_ID,
) -> SessionMessagesResponse:
    """读取某会话的历史消息，按发生顺序返回。"""
    session = await get_session(
        request.app.state.session_service, user_id=user_id, session_id=session_id
    )
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return SessionMessagesResponse(
        session_id=session.id,
        user_id=user_id,
        messages=[HistoryMessage(**message) for message in events_to_messages(session)],
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def read_session(
    session_id: str,
    request: Request,
    user_id: str = DEFAULT_USER_ID,
) -> SessionResponse:
    """查询会话是否存在。"""
    session = await get_session(
        request.app.state.session_service, user_id=user_id, session_id=session_id
    )
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return SessionResponse(session_id=session.id, user_id=user_id)