"""对话收尾自动快照的接口测试。

覆盖「一轮改动后恰好产生一个版本」「内容未变则不重复产生版本」「纯问答不产生版本」
「连续两轮各自改动各产生一个版本」（见 specs/app-versions/spec.md 的「每轮自动快照」
与 design.md 决策 8）。

沙箱与版本根目录指向临时目录；用假 Runner 模拟模型调用写文件工具。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api import chat as api_chat
from app.config import load_settings
from app.schemas import ChatRequest
from app.services import versions, workspace

SETTINGS = load_settings(
    {
        "LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
        "LLM_MODEL": "glm-4.5-flash",
        "LLM_API_KEY": "sk-test-1234567890",
        "SESSION_BACKEND": "memory",
    }
)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(versions, "VERSIONS_ROOT", tmp_path / "versions")
    return tmp_path


def make_user(username: str = "alice"):
    return SimpleNamespace(
        username=username, role="user", token="t-1", session_user_id=f"user:{username}"
    )


class WritingRunner:
    """模拟「调用写文件工具」的假 Runner：产出文本事件，并把给定文件写进沙箱。"""

    def __init__(self, writes=()):
        self.writes = list(writes)

    async def run_async(self, **kwargs):
        for path, content in self.writes:
            workspace.write_file(kwargs["session_id"], path, content, SETTINGS)
        yield SimpleNamespace(
            content=SimpleNamespace(parts=[SimpleNamespace(text="已生成应用")]),
            partial=False,
            id="evt-1",
            error_code=None,
            author="code_assistant",
        )


class FakeSessionService:
    async def append_event(self, session, event):
        return event


def run_turn(monkeypatch, session_id: str, runner) -> list[dict]:
    """驱动一轮对话并返回解析后的 SSE 帧。"""
    session = SimpleNamespace(id=session_id, events=[])

    async def fake_get_session(session_service, *, user_id, session_id):
        return session

    monkeypatch.setattr(api_chat, "get_session", fake_get_session)

    async def scenario():
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    runner=runner,
                    session_service=FakeSessionService(),
                    settings=SETTINGS,
                )
            )
        )
        response = await api_chat.chat(
            request,
            ChatRequest(message="做一个俄罗斯方块小游戏", session_id=session_id),
            make_user(),
        )
        chunks = [chunk async for chunk in response.body_iterator]
        return [json.loads(chunk[len("data: ") :].strip()) for chunk in chunks]

    return asyncio.run(scenario())


def version_ids(session_id: str) -> list[str]:
    return [record["version_id"] for record in versions.list_versions(session_id)]


# --- 6.1 收尾挂点 ---


def test_a_changed_turn_creates_exactly_one_version(monkeypatch, roots):
    frames = run_turn(
        monkeypatch, "s-1", WritingRunner([("index.html", "<h1>俄罗斯方块</h1>")])
    )

    assert version_ids("s-1") == ["0001"]
    assert frames[-1]["type"] == "done"


def test_a_pure_question_turn_creates_no_version(monkeypatch, roots):
    run_turn(monkeypatch, "s-1", WritingRunner())

    assert version_ids("s-1") == []


def test_two_changed_turns_create_two_versions(monkeypatch, roots):
    run_turn(monkeypatch, "s-1", WritingRunner([("index.html", "<h1>A</h1>")]))
    run_turn(monkeypatch, "s-1", WritingRunner([("index.html", "<h1>B</h1>")]))

    assert version_ids("s-1") == ["0002", "0001"]


def test_an_unchanged_turn_creates_no_extra_version(monkeypatch, roots):
    """内容与本轮快照一致时不再产生版本，避免同一状态反复留档。"""
    run_turn(monkeypatch, "s-1", WritingRunner([("index.html", "<h1>A</h1>")]))
    run_turn(monkeypatch, "s-1", WritingRunner([("index.html", "<h1>A</h1>")]))

    assert version_ids("s-1") == ["0001"]


def test_snapshots_are_per_session(monkeypatch, roots):
    run_turn(monkeypatch, "s-1", WritingRunner([("index.html", "A")]))
    run_turn(monkeypatch, "s-2", WritingRunner([("index.html", "B")]))

    assert version_ids("s-1") == ["0001"]
    assert version_ids("s-2") == ["0001"]