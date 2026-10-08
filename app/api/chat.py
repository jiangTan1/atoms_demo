"""对话接口。

POST /api/chat：以 text/event-stream 返回流式帧，
并设置 Cache-Control: no-cache 与 X-Accel-Buffering: no 以避免代理缓冲。
要求登录，会话归属一律取自登录态（见 specs/access-control/spec.md）。

对话流正常结束后比对会话沙箱的指纹，有变化时留下一份版本快照，
使「每轮自动快照」不依赖模型事件语义（见 design.md 决策 8）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.auth import CurrentUser, current_user
from app.schemas import ChatRequest
from app.services import chat as chat_service
from app.services import versions
from app.services.runner import create_session, get_session

router = APIRouter(prefix="/api", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def snapshot_if_changed(request: Request, session_id: str) -> None:
    """一轮对话的收尾动作：沙箱内容有变化时留下一个版本。

    比对的是沙箱的可观测内容（文件清单 + 各文件哈希）而不是「本轮是否调用过写文件」，
    因此删除文件、覆盖为空等情形同样会被记录下来。快照是收尾增强，
    失败时只少留一个版本，不影响已经产出的回复。
    """
    try:
        versions.snapshot_if_changed(session_id, request.app.state.settings)
    except Exception:  # noqa: BLE001 - 落盘异常不应污染已完成的对话流
        pass


@router.post("/chat")
async def chat(
    request: Request,
    payload: ChatRequest,
    user: CurrentUser = Depends(current_user),
) -> StreamingResponse:
    """流式对话：帧格式见 app/schemas.py 的 SSE 帧定义。"""
    runner = request.app.state.runner
    session_service = request.app.state.session_service
    user_id = user.session_user_id

    session_id = payload.session_id
    if session_id:
        session = await get_session(
            session_service, user_id=user_id, session_id=session_id
        )
        if session is None:
            raise HTTPException(
                status_code=404, detail=f"会话 {session_id} 不存在，请先新建会话"
            )
    else:
        session = await create_session(session_service, user_id=user_id)
        session_id = session.id

    # 追问轮次由服务端从会话事件推导，不依赖模型自己计数（见 design.md 决策 4）
    clarify_rounds = chat_service.count_clarify_rounds(session)
    message = chat_service.compose_user_message(
        payload.message, payload.target_language, clarify_rounds
    )

    if clarify_rounds >= chat_service.MAX_CLARIFY_ROUNDS:
        # 已达追问上限：不再请求模型，直接返回固定结束语（见 design.md 决策 6）
        limit_event = chat_service.build_event(
            "code_assistant", chat_service.CLARIFY_ROUND_LIMIT_MESSAGE
        )
        try:
            # 补写该轮的用户消息与结束语（用户消息与其他轮次一致，写入注入前缀后的文本），
            # 保证刷新后历史与刚才所见一致
            await session_service.append_event(
                session, chat_service.build_event("user", message)
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

    async def event_stream():
        async for frame in chat_service.stream_frames(
            runner,
            user_id=user_id,
            session_id=session_id,
            message=message,
        ):
            yield f"data: {frame.model_dump_json()}\n\n"

        # 完整帧已产出，本轮改动至此定型：按沙箱指纹留档（见 design.md 决策 8）
        snapshot_if_changed(request, session_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)