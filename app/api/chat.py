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

    # 追问轮次由服务端从会话事件推导，不依赖模型自己计数（见 design.md 决策 4）
    clarify_rounds = chat_service.count_clarify_rounds(session)

    if clarify_rounds >= chat_service.MAX_CLARIFY_ROUNDS:
        # 已达追问上限：不再请求模型，直接返回固定结束语（见 design.md 决策 6）
        limit_event = chat_service.build_event(
            "code_assistant", chat_service.CLARIFY_ROUND_LIMIT_MESSAGE
        )
        try:
            # 补写该轮的用户消息与结束语，保证刷新后历史与刚才所见一致
            await session_service.append_event(
                session, chat_service.build_event("user", payload.message)
            )
            await session_service.append_event(session, limit_event)
        except Exception:  # noqa: BLE001 - 落盘失败时退化为不入库，回复本身仍照常返回
            pass

        async def limit_stream():
            for frame in chat_service.limit_frames(session_id, limit_event.id):
                yield f"data: {frame.model_dump_json()}\n\n"

        return StreamingResponse(
            limit_stream(), media_type="text/event-stream", headers=SSE_HEADERS
        )

    message = chat_service.compose_user_message(
        payload.message, payload.target_language, clarify_rounds
    )

    async def event_stream():
        async for frame in chat_service.stream_frames(
            runner,
            user_id=payload.user_id,
            session_id=session_id,
            message=message,
        ):
            yield f"data: {frame.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)