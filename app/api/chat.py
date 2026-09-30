"""对话接口。

POST /api/chat：以 text/event-stream 返回流式帧，
并设置 Cache-Control: no-cache 与 X-Accel-Buffering: no 以避免代理缓冲。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest
from app.services import chat as chat_service
from app.services.runner import create_session, get_session

router = APIRouter(prefix="/api", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.post("/chat")
async def chat(request: Request, payload: ChatRequest) -> StreamingResponse:
    """流式对话：帧格式见 app/schemas.py 的 SSE 帧定义。"""
    runner = request.app.state.runner
    session_service = request.app.state.session_service

    session_id = payload.session_id
    if session_id:
        session = await get_session(
            session_service, user_id=payload.user_id, session_id=session_id
        )
        if session is None:
            raise HTTPException(
                status_code=404, detail=f"会话 {session_id} 不存在，请先新建会话"
            )
    else:
        session = await create_session(session_service, user_id=payload.user_id)
        session_id = session.id

    message = chat_service.compose_user_message(payload.message, payload.target_language)

    async def event_stream():
        async for frame in chat_service.stream_frames(
            runner,
            user_id=payload.user_id,
            session_id=session_id,
            message=message,
        ):
            yield f"data: {frame.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)