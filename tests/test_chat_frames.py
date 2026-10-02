"""SSE 帧转换与历史还原的单元测试。

覆盖增量文本 / 最终文本 / 异常转 error 三类帧用例，以及会话事件→历史消息的还原。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.chat import (
    CLARIFY_MARKER,
    FrameBuilder,
    compose_user_message,
    count_clarify_rounds,
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


def test_compose_user_message_injects_clarify_round():
    assert compose_user_message("帮我优化", "java", 0) == "[目标语言：Java]\n\n帮我优化"
    assert compose_user_message("帮我优化", "java", 2) == (
        "[目标语言：Java]\n[澄清轮次：2/5]\n\n帮我优化"
    )


def test_events_to_messages_strips_language_and_round_prefixes():
    """语言与轮次前缀可能同时存在，回放历史时都不应外泄。"""
    session = SimpleNamespace(
        events=[
            make_history_event("user", compose_user_message("用 Java 写单例", "java", 3)),
            make_history_event("code_assistant", "好的"),
        ]
    )

    assert events_to_messages(session) == [
        {"role": "user", "text": "用 Java 写单例"},
        {"role": "assistant", "text": "好的"},
    ]


def test_events_to_messages_hides_clarify_marker():
    """历史回放同样不能出现标记。"""
    session = SimpleNamespace(
        events=[
            make_history_event("user", "帮我优化"),
            make_history_event("code_assistant", f"{CLARIFY_MARKER}\n请问目标语言是？"),
        ]
    )

    assert events_to_messages(session) == [
        {"role": "user", "text": "帮我优化"},
        {"role": "assistant", "text": "请问目标语言是？"},
    ]


def test_count_clarify_rounds_is_zero_without_clarify_replies():
    assert count_clarify_rounds(SimpleNamespace(events=[])) == 0
    session = SimpleNamespace(
        events=[make_history_event("user", "解释这段代码")]
    )
    assert count_clarify_rounds(session) == 0


def test_count_clarify_rounds_counts_consecutive_clarify_replies():
    """用户事件只起分隔作用，跨用户事件仍属连续的追问链。"""
    session = SimpleNamespace(
        events=[
            make_history_event("user", "帮我优化一下"),
            make_history_event("code_assistant", f"{CLARIFY_MARKER}\n请问目标语言是？"),
            make_history_event("user", "Java"),
            make_history_event("code_assistant", f"{CLARIFY_MARKER}\n请问优化哪方面？"),
        ]
    )

    assert count_clarify_rounds(session) == 2


def test_count_clarify_rounds_stops_at_substantive_answer():
    """中间插入了实质回答，追问链断开，只应统计最近这一段。"""
    session = SimpleNamespace(
        events=[
            make_history_event("user", "帮我优化"),
            make_history_event("code_assistant", f"{CLARIFY_MARKER}\n请给我代码"),
            make_history_event("user", "```java\nclass A {}\n```"),
            make_history_event("code_assistant", "```java\nclass B {}\n```"),
            make_history_event("user", "再优化一下"),
            make_history_event("code_assistant", f"{CLARIFY_MARKER}\n优化哪方面？"),
        ]
    )

    assert count_clarify_rounds(session) == 1


def test_clarify_marker_is_stripped_across_partial_slices():
    """标记被增量切片时不能闪现半截，判定完成后再照常下发。"""
    builder = FrameBuilder(session_id="s-1")

    assert builder.consume(make_event("[[CLAR", partial=True)) == []
    assert builder.consume(make_event("IFY]]", partial=True)) == []

    frames = builder.consume(make_event("\n请问目标语言是？", partial=True))
    assert [frame.model_dump() for frame in frames] == [
        {"type": "text", "data": "\n请问目标语言是？", "partial": True}
    ]

    final = builder.consume(make_event("整段", partial=False, event_id="evt-9"))
    assert [frame.model_dump() for frame in final] == [
        {"type": "text", "data": "\n请问目标语言是？", "partial": False}
    ]


def test_reply_starting_with_bracket_is_not_swallowed():
    """首字符为 `[` 的普通回复不能被判定缓冲吞掉。"""
    builder = FrameBuilder(session_id="s-1")

    assert builder.consume(make_event("[", partial=True)) == []

    frames = builder.consume(make_event("注意] 这里有个坑", partial=True))
    assert [frame.model_dump() for frame in frames] == [
        {"type": "text", "data": "[注意] 这里有个坑", "partial": True}
    ]


def test_single_shot_reply_with_marker_is_stripped():
    """整段一次性返回（没有增量帧）且以标记开头时同样要剥离。"""
    builder = FrameBuilder(session_id="s-1")

    frames = builder.consume(
        make_event(f"{CLARIFY_MARKER}\n请问要哪个语言？", partial=False)
    )

    assert [frame.model_dump() for frame in frames] == [
        {"type": "text", "data": "\n请问要哪个语言？", "partial": False}
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