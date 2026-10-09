"""对话接口的单元测试。

覆盖轮次注入与追问达到上限时的短路行为（见 design.md 决策 5、6），
用一个假 Runner 替代真实模型，确认上限轮不再请求模型、正常轮次会被注入轮次前缀，
以及会话归属取自登录态并带 `user:` 前缀（见本次变更的 specs/access-control/spec.md）。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.api import chat as api_chat
from app.schemas import ChatRequest
from app.services.chat import CLARIFY_MARKER, CLARIFY_ROUND_LIMIT_MESSAGE


def make_user(username="alice"):
    """直连路由函数时替代鉴权依赖的当前身份。"""
    return SimpleNamespace(
        username=username, role="user", token="t-1", session_user_id=f"user:{username}"
    )


def make_history_event(author: str, text: str):
    return SimpleNamespace(
        author=author,
        content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
        partial=False,
        error_code=None,
    )


def make_clarify_events(rounds: int):
    """构造 rounds 条连续的追问回复，穿插对应的用户消息。"""
    events = []
    for i in range(rounds):
        events.append(make_history_event("user", f"补充 {i}"))
        events.append(make_history_event("code_assistant", f"{CLARIFY_MARKER}\n请补充 {i}"))
    return events


class ScriptedRunner:
    """按脚本产出事件的假 Runner，同时记录收到的调用参数。"""

    def __init__(self, events):
        self.events = events
        self.kwargs = None

    async def run_async(self, **kwargs):
        self.kwargs = kwargs
        for event in self.events:
            yield event


class ExplodingRunner:
    """被调用即失败，用于确认上限轮不会请求模型。"""

    async def run_async(self, **kwargs):
        raise AssertionError("追问达到上限时不应请求模型")
        yield  # pragma: no cover - 仅为让方法成为异步生成器


class FakeSessionService:
    def __init__(self):
        self.appended = []

    async def append_event(self, session, event):
        self.appended.append(event)
        session.events.append(event)
        return event


def make_request(runner, session_service):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                runner=runner,
                session_service=session_service,
                # 接口层会把时限透传给服务层，这里给一个最小可用的配置替身
                settings=SimpleNamespace(chat_timeout_seconds=120),
            )
        )
    )


async def collect_frames(response):
    chunks = [chunk async for chunk in response.body_iterator]
    return [json.loads(chunk[len("data: ") :].strip()) for chunk in chunks]


def run_chat(monkeypatch, *, session, runner, session_service, message="随便吧", language=None):
    async def fake_get_session(session_service_, *, user_id, session_id):
        return session

    monkeypatch.setattr(api_chat, "get_session", fake_get_session)

    async def scenario():
        payload = ChatRequest(
            message=message, session_id="s-1", target_language=language
        )
        response = await api_chat.chat(
            make_request(runner, session_service), payload, make_user()
        )
        return await collect_frames(response)

    return asyncio.run(scenario())


def test_normal_turn_injects_clarify_round_prefix(monkeypatch):
    session = SimpleNamespace(id="s-1", events=make_clarify_events(1))
    runner = ScriptedRunner(
        [SimpleNamespace(content=None, partial=False, id="evt-1")]
    )

    frames = run_chat(
        monkeypatch,
        session=session,
        runner=runner,
        session_service=FakeSessionService(),
        message="Java",
        language="java",
    )

    sent = runner.kwargs["new_message"].parts[0].text
    assert sent == "[目标语言：Java]\n[澄清轮次：1/5]\n\nJava"
    assert frames[-1]["type"] == "done"


def test_chat_uses_the_logged_in_identity(monkeypatch):
    """归属者取自登录态并加 user: 前缀，客户端不再参与指定。"""
    session = SimpleNamespace(id="s-1", events=[])
    runner = ScriptedRunner([SimpleNamespace(content=None, partial=False, id="evt-1")])

    run_chat(
        monkeypatch,
        session=session,
        runner=runner,
        session_service=FakeSessionService(),
        message="写个单例",
    )

    assert runner.kwargs["user_id"] == "user:alice"


def test_chat_short_circuits_when_clarify_limit_reached(monkeypatch):
    session = SimpleNamespace(id="s-1", events=make_clarify_events(5))
    session_service = FakeSessionService()

    frames = run_chat(
        monkeypatch,
        session=session,
        runner=ExplodingRunner(),
        session_service=session_service,
        message="就随便吧",
    )

    assert frames[0] == {
        "type": "text",
        "data": CLARIFY_ROUND_LIMIT_MESSAGE,
        "partial": False,
    }
    assert frames[-1]["type"] == "done"
    # 该轮的用户消息与结束语都被补写进会话，刷新后历史仍在
    assert [event.author for event in session_service.appended] == [
        "user",
        "code_assistant",
    ]
    assert session_service.appended[-1].content.parts[0].text == CLARIFY_ROUND_LIMIT_MESSAGE