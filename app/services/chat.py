"""事件流服务。

以 RunConfig(streaming_mode=StreamingMode.SSE) 驱动 runner.run_async，
并把 ADK Event 归一化为 text / error / done 三类 SSE 帧（协议见 design.md 决策 4）。

文本累积放在服务端：partial 事件按增量下发，最终事件补一个 partial=False 的完整帧，
这样前端即使在增量丢帧的情况下也能拿到完整内容。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator

from google.adk.events import Event
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

# 澄清追问：提示词/服务端约定的控制标记与轮次上限（见 design.md 决策 3、6）
CLARIFY_MARKER = "[[CLARIFY]]"
MAX_CLARIFY_ROUNDS = 5
CLARIFY_ROUND_LIMIT_MESSAGE = (
    "抱歉，经过 5 次追问我仍无法准确理解你的意图。"
    "你可以换一种说法重新描述，或点击「新建会话」开始新的对话。"
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


def compose_user_message(
    message: str, target_language: str | None, clarify_round: int = 0
) -> str:
    """把目标语言选择与当前澄清轮次拼进用户消息，供 Agent 遵循。

    clarify_round 为此前已发生的追问次数（0 时不注入前缀），提示词据此判断是否已到追问上限。
    """
    prefixes = []
    if target_language:
        prefixes.append(f"[目标语言：{TARGET_LANGUAGES[target_language]}]")
    if clarify_round:
        prefixes.append(f"[澄清轮次：{clarify_round}/{MAX_CLARIFY_ROUNDS}]")
    if not prefixes:
        return message
    return "\n".join(prefixes) + f"\n\n{message}"


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


# 还原历史时去掉 compose_user_message 注入的内部前缀（语言 / 轮次可能同时存在且可重复），
# 避免页面上出现内部标记
_INTERNAL_PREFIX_RE = re.compile(r"^(?:\[(?:目标语言|澄清轮次)：[^\]]*\]\s*)+")


def count_clarify_rounds(session) -> int:
    """推导当前会话已发生的澄清追问轮次。

    从最新事件向前数连续出现的「带澄清标记的助手回复」，遇到第一个不带标记的助手回复即停止
    （该回复是实质回答，追问链已断开）；用户事件只起分隔作用，不参与计数也不中断计数。
    """
    rounds = 0
    for event in reversed(getattr(session, "events", None) or []):
        if getattr(event, "error_code", None) or getattr(event, "partial", False):
            continue
        text = extract_text(event).strip()
        if not text:
            continue
        if getattr(event, "author", "") == "user":
            continue
        if text.startswith(CLARIFY_MARKER):
            rounds += 1
        else:
            break
    return rounds


def strip_clarify_marker(text: str) -> str:
    """去掉助手回复开头的澄清标记，标记对使用者始终不可见。

    text 需为已去除首尾空白的文本；标记独占第一行，剥离后顺带吃掉其后的空白。
    """
    if not text.startswith(CLARIFY_MARKER):
        return text
    return text[len(CLARIFY_MARKER) :].lstrip()


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
            messages.append({"role": "user", "text": _INTERNAL_PREFIX_RE.sub("", text)})
        else:
            messages.append({"role": "assistant", "text": strip_clarify_marker(text)})
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
    """把一个会话轮次中的 ADK Event 序列归一化为 SSE 帧。

    回复开头的澄清标记必须对使用者不可见：增量文本会把 11 个字符的标记切成多片，
    因此先缓存开头、判定完成后再放行（见 design.md 决策 3）。
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.message_id = ""
        self.error_emitted = False
        self._raw = ""  # 本轮回复的原始文本（含可能存在的开头标记）
        self._offset = 0  # 剥离掉的标记长度
        self._emitted_upto = 0  # 已下发的文本在 _raw 中的绝对位置
        self._head_done = False

    def _settle_head(self, *, force: bool) -> None:
        """判定回复开头是否为澄清标记；force 表示事件流已结束，必须给出结论。"""
        if self._head_done:
            return
        stripped = self._raw.lstrip()
        if not stripped:
            # 只见到空白：结束前继续等待，结束后按普通文本处理
            if force:
                self._head_done = True
            return
        leading = len(self._raw) - len(stripped)
        if stripped.startswith(CLARIFY_MARKER):
            self._offset = leading + len(CLARIFY_MARKER)
            self._head_done = True
        elif force or not CLARIFY_MARKER.startswith(stripped):
            # 确认与标记不符：整体照常放行，不吞掉正文
            self._head_done = True

    def _drain(self) -> list[Frame]:
        """下发自上次之后新增的文本，自动跳过被剥离的标记。"""
        start = max(self._emitted_upto, self._offset)
        if start >= len(self._raw):
            return []
        delta = self._raw[start:]
        self._emitted_upto = len(self._raw)
        return [TextFrame(data=delta, partial=True)]

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
            self._raw += text
            self._settle_head(force=False)
            # 开头仍可能是标记的一部分（且已不只有空白）时先不下发，避免半截标记闪现
            if not self._head_done and self._raw.strip():
                return []
            return self._drain()

        # 最终事件：此前没有任何增量时以整段文本为准，否则用累积文本补完整帧
        if not self._raw:
            self._raw = text
        self._settle_head(force=True)
        return [TextFrame(data=self._raw[self._offset :], partial=False)]

    def done(self) -> DoneFrame:
        return DoneFrame(data=DoneData(session_id=self.session_id, message_id=self.message_id))


def build_user_content(message: str) -> genai_types.Content:
    return genai_types.Content(role="user", parts=[genai_types.Part(text=message)])


def build_event(author: str, text: str) -> Event:
    """构造一个可落盘的纯文本事件，用于服务端短路时把该轮补写进会话。"""
    return Event(
        author=author,
        invocation_id=uuid.uuid4().hex,
        content=genai_types.Content(
            role="user" if author == "user" else "model",
            parts=[genai_types.Part(text=text)],
        ),
    )


def limit_frames(session_id: str, message_id: str) -> list[Frame]:
    """追问达到上限时的固定结束语帧（见 design.md 决策 6）。"""
    return [
        TextFrame(data=CLARIFY_ROUND_LIMIT_MESSAGE, partial=False),
        DoneFrame(data=DoneData(session_id=session_id, message_id=message_id)),
    ]


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