"""SSE 帧转换与历史还原的单元测试。

覆盖增量文本 / 最终文本 / 异常转 error 三类帧用例，以及会话事件→历史消息的还原。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.chat import (
    FrameBuilder,
    compose_user_message,
    error_frame_from_exception,
    events_to_messages,
)


def make_event(text: str | None = None, *, partial: bool = True, event_id: str = "evt-1"):
    """构造一个结构等价于 ADK Event 的假事件。"""
    content = (
        SimpleNamespace(parts=[SimpleNamespace(text=text)]) if text is not None else None
    )
    return SimpleNamespace(content=content, partial=partial, id=event_id)


def test_partial_text_becomes_incremental_frame():
    builder = FrameBuilder(session_id="s-1")

    frames = builder.consume(make_event("你好", partial=True))

    assert [frame.model_dump() for frame in frames] == [
        {"type": "text", "data": "你好", "partial": True}
    ]


def test_final_event_carries_full_accumulated_text():
    builder = FrameBuilder(session_id="s-1")
    builder.consume(make_event("这段", partial=True))
    builder.consume(make_event("代码", partial=True))

    frames = builder.consume(make_event("这段代码没问题。", partial=False, event_id="evt-9"))
    done = builder.done()

    assert [frame.model_dump() for frame in frames] == [
        {"type": "text", "data": "这段代码", "partial": False}
    ]
    assert done.model_dump() == {
        "type": "done",
        "data": {"session_id": "s-1", "message_id": "evt-9"},
    }


def test_exception_becomes_error_frame():
    class AuthenticationError(Exception):
        status_code = 401

    auth_frame = error_frame_from_exception(AuthenticationError("invalid api key"))
    assert auth_frame.model_dump()["type"] == "error"
    assert auth_frame.data.code == "auth_error"

    network_frame = error_frame_from_exception(ConnectionError("Connection refused"))
    assert network_frame.data.code == "network_error"


def test_error_event_becomes_readable_error_frame():
    builder = FrameBuilder(session_id="s-1")
    event = make_event(None, partial=False)
    event.error_code = "AuthenticationError"
    event.error_message = "Error code: 401 - 令牌已过期或验证不正确"

    frames = builder.consume(event)

    assert frames[0].type == "error"
    assert frames[0].data.code == "auth_error"
    assert "LLM_API_KEY" in frames[0].data.message
    assert builder.error_emitted is True


def make_history_event(author: str, text: str | None, *, partial: bool = False):
    return SimpleNamespace(
        author=author,
        content=SimpleNamespace(parts=[SimpleNamespace(text=text)]) if text is not None else None,
        partial=partial,
        error_code=None,
    )


def test_events_to_messages_restores_multi_turn_history():
    session = SimpleNamespace(
        events=[
            make_history_event("user", compose_user_message("用 Java 写单例", "java")),
            make_history_event("code_assistant", "```java\nclass A {}\n```"),
            make_history_event("user", "改成懒加载"),
            make_history_event("code_assistant", "```java\nclass B {}\n```"),
        ]
    )

    assert events_to_messages(session) == [
        {"role": "user", "text": "用 Java 写单例"},
        {"role": "assistant", "text": "```java\nclass A {}\n```"},
        {"role": "user", "text": "改成懒加载"},
        {"role": "assistant", "text": "```java\nclass B {}\n```"},
    ]


def test_events_to_messages_skips_intermediate_and_error_events():
    errored = make_history_event("code_assistant", None)
    errored.error_code = "AuthenticationError"

    session = SimpleNamespace(
        events=[
            make_history_event("user", "解释这段代码"),
            make_history_event("code_assistant", "这段", partial=True),
            make_history_event("code_assistant", "   "),
            errored,
            make_history_event("code_assistant", "这段代码的作用是……"),
        ]
    )

    assert events_to_messages(session) == [
        {"role": "user", "text": "解释这段代码"},
        {"role": "assistant", "text": "这段代码的作用是……"},
    ]


def test_extract_text_skips_thought_parts():
    """模型推理与回答常常同处一个事件的 parts 中，推理不应外泄。"""
    event = SimpleNamespace(
        author="code_assistant",
        content=SimpleNamespace(
            parts=[
                SimpleNamespace(text="The user asks me to...", thought=True),
                SimpleNamespace(text="这段代码的作用是解释装饰器。"),
            ]
        ),
        partial=False,
        error_code=None,
    )

    assert events_to_messages(SimpleNamespace(events=[event])) == [
        {"role": "assistant", "text": "这段代码的作用是解释装饰器。"}
    ]