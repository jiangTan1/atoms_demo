"""事件流服务。

以 RunConfig(streaming_mode=StreamingMode.SSE) 驱动 runner.run_async，
并把 ADK Event 归一化为 text / error / done 三类 SSE 帧（协议见 design.md 决策 4）。

文本累积放在服务端：partial 事件按增量下发，最终事件补一个 partial=False 的完整帧，
这样前端即使在增量丢帧的情况下也能拿到完整内容。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from google.adk.runners import RunConfig, Runner
from google.genai import types as genai_types

from app.schemas import (
    TARGET_LANGUAGES,
    DoneData,
    DoneFrame,
    ErrorData,
    ErrorFrame,
    Frame,
    TextFrame,
)

# ADK 2.x 默认不流式，网页场景必须显式打开 SSE（等价于 StreamingMode.SSE）
STREAM_RUN_CONFIG = RunConfig(streaming_mode="sse")

# 错误类别 -> 面向使用者的说明（model-integration spec 要求区分网络不可达与鉴权失败）
ERROR_MESSAGES = {
    "auth_error": "访问凭据被模型端点拒绝，请检查 .env 中的 LLM_API_KEY 是否正确、是否已过期。",
    "network_error": "无法连接到模型端点，请检查 .env 中的 LLM_BASE_URL、本机网络或代理设置。",
    "upstream_error": "模型端点返回了错误响应。",
}

_AUTH_STATUS_CODES = {401, 403}
_AUTH_MARKERS = (
    "authenticationerror",
    "permissiondenied",
    "invalid api key",
    "incorrect api key",
    "unauthorized",
    "invalid_api_key",
)
_NETWORK_MARKERS = (
    "connection",
    "timeout",
    "timed out",
    "unreachable",
    "getaddrinfo",
    "ssl",
    "proxy",
    "apiconnectionerror",
)


def compose_user_message(message: str, target_language: str | None) -> str:
    """把目标语言选择拼进用户消息，供 Agent 遵循。"""
    if not target_language:
        return message
    display = TARGET_LANGUAGES[target_language]
    return f"[目标语言：{display}]\n\n{message}"


def extract_text(event) -> str:
    """取出事件中的文本增量。

    忽略工具调用等非文本部件，并跳过 thought 部件——模型的内部推理不属于给使用者看的内容，
    落盘的事件里两者会同时存在（例如 glm-4.5-flash 会把推理过程一并放在 parts 中）。
    """
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    return "".join(
        part.text
        for part in parts
        if getattr(part, "text", None) and not getattr(part, "thought", False)
    )


# 还原历史时去掉 compose_user_message 加的语言前缀，避免页面上出现内部标记
_LANGUAGE_PREFIX_RE = re.compile(r"^\[目标语言：[^\]]*\]\s*")


def events_to_messages(session) -> list[dict]:
    """把会话事件还原为前端可渲染的历史消息。

    ADK 一轮对话会落盘两条事件（user 原文 + 助手最终文本），这里按作者区分角色，
    并跳过流式中间态、空内容与只含错误的记录（见 design.md 决策 2）。
    """
    messages: list[dict] = []
    for event in getattr(session, "events", None) or []:
        if getattr(event, "error_code", None) or getattr(event, "partial", False):
            continue
        text = extract_text(event).strip()
        if not text:
            continue
        if getattr(event, "author", "") == "user":
            messages.append({"role": "user", "text": _LANGUAGE_PREFIX_RE.sub("", text)})
        else:
            messages.append({"role": "assistant", "text": text})
    return messages


def classify_failure(
    status: int | None, name: str, detail: str
) -> tuple[str, str]:
    """把失败信息归类为可诊断的错误码与说明，区分鉴权失败与网络不可达。"""
    haystack = f"{name} {detail}".lower()

    if status in _AUTH_STATUS_CODES or any(m in haystack for m in _AUTH_MARKERS):
        code = "auth_error"
    elif any(m in haystack for m in _NETWORK_MARKERS):
        code = "network_error"
    else:
        code = "upstream_error"

    return code, f"{ERROR_MESSAGES[code]}（原始信息：{detail}）"


def classify_error(exc: BaseException) -> tuple[str, str]:
    """把异常归类为可诊断的错误码与说明。"""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    detail = str(exc).strip() or repr(exc)
    return classify_failure(status, type(exc).__name__, detail)


def error_frame_from_exception(exc: BaseException) -> ErrorFrame:
    code, message = classify_error(exc)
    return ErrorFrame(data=ErrorData(code=code, message=message))


def error_frame_from_event(event) -> ErrorFrame:
    """ADK 以事件形式上报的模型错误，同样归一化为可诊断的错误帧。"""
    detail = str(getattr(event, "error_message", "") or "模型返回了错误事件")
    code, message = classify_failure(None, str(getattr(event, "error_code", "")), detail)
    return ErrorFrame(data=ErrorData(code=code, message=message))


class FrameBuilder:
    """把一个会话轮次中的 ADK Event 序列归一化为 SSE 帧。"""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.message_id = ""
        self.error_emitted = False
        self._buffer: list[str] = []

    def consume(self, event) -> list[Frame]:
        """消费一个 Event，返回它对应的帧（可能为空）。"""
        if getattr(event, "error_code", None):
            self.error_emitted = True
            return [error_frame_from_event(event)]

        event_id = getattr(event, "id", None)
        if event_id:
            self.message_id = str(event_id)

        text = extract_text(event)
        if not text:
            return []

        if getattr(event, "partial", False):
            self._buffer.append(text)
            return [TextFrame(data=text, partial=True)]

        # 最终事件：用服务端累积的文本补一个完整帧，前端可据此校正内容
        return [TextFrame(data="".join(self._buffer) or text, partial=False)]

    def done(self) -> DoneFrame:
        return DoneFrame(data=DoneData(session_id=self.session_id, message_id=self.message_id))


def build_user_content(message: str) -> genai_types.Content:
    return genai_types.Content(role="user", parts=[genai_types.Part(text=message)])


async def stream_frames(
    runner: Runner,
    *,
    user_id: str,
    session_id: str,
    message: str,
) -> AsyncIterator[Frame]:
    """驱动一次流式对话，产出 text / error / done 帧。"""
    builder = FrameBuilder(session_id)
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=build_user_content(message),
            run_config=STREAM_RUN_CONFIG,
        ):
            for frame in builder.consume(event):
                yield frame
    except Exception as exc:  # noqa: BLE001 - 需要把任意上游异常转成可诊断的 error 帧
        # ADK 可能已经用错误事件上报过同一次失败，避免重复提示
        if not builder.error_emitted:
            yield error_frame_from_exception(exc)
        return

    yield builder.done()