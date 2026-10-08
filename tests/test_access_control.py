"""受保护接口的访问控制与资源归属测试。

用「认证 + 会话 + 对话 + 打包下载」四个路由组成的最小应用，
配假的会话服务与 Runner，覆盖未登录一律 401、会话与沙箱按登录用户隔离、
他人会话按不存在处理（见 openspec/changes/add-user-authentication/tasks.md 的第 4 组任务）。
"""

from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api import chat as chat_api
from app.api import sessions as sessions_api
from app.api import workspace as workspace_api
from app.schemas import ChatRequest, SessionCreateRequest
from app.services import accounts
from app.services import chat as chat_service
from app.services import workspace
from app.services.accounts import AccountService

ALICE_ID = "user:alice"
BOB_ID = "user:bob"


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(accounts, "_HASH_ITERATIONS", 1000)


class FakeSessionService:
    """只保留归属信息的假会话服务，键为 (user_id, session_id)。"""

    def __init__(self):
        self.store: dict[tuple[str, str], SimpleNamespace] = {}
        self.created: list[tuple[str, str]] = []

    async def create_session(self, *, app_name, user_id, session_id=None):
        sid = session_id or f"session-{len(self.store) + 1}"
        session = SimpleNamespace(
            id=sid, events=[], last_update_time=1.0, app_name=app_name, user_id=user_id
        )
        self.store[(user_id, sid)] = session
        self.created.append((user_id, sid))
        return session

    async def get_session(self, *, app_name, user_id, session_id):
        return self.store.get((user_id, session_id))

    async def list_sessions(self, *, app_name, user_id):
        return SimpleNamespace(
            sessions=[session for (uid, _), session in self.store.items() if uid == user_id]
        )

    async def append_event(self, session, event):
        session.events.append(event)
        return event

    def seed(self, user_id: str, session_id: str, *messages):
        session = SimpleNamespace(
            id=session_id,
            events=[chat_service.build_event(role, text) for role, text in messages],
            last_update_time=2.0,
        )
        self.store[(user_id, session_id)] = session
        return session


class EchoRunner:
    """记录调用参数的假 Runner，固定回复一段文本。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def run_async(self, **kwargs):
        self.calls.append(kwargs)
        yield SimpleNamespace(
            content=SimpleNamespace(parts=[SimpleNamespace(text="你好")]),
            partial=False,
            id="evt-1",
            error_code=None,
            author="code_assistant",
        )


@pytest.fixture
def session_service():
    return FakeSessionService()


@pytest.fixture
def runner():
    return EchoRunner()


@pytest.fixture
def app(tmp_path, monkeypatch, session_service, runner):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path / "workspace")

    accounts_service = AccountService(tmp_path / "users.db")
    accounts_service.ensure_admin("root", "root")

    application = FastAPI()
    application.state.settings = SimpleNamespace(auth_cookie_secure=False)
    application.state.accounts = accounts_service
    application.state.session_service = session_service
    application.state.runner = runner
    application.include_router(auth_api.router)
    application.include_router(sessions_api.router)
    application.include_router(chat_api.router)
    application.include_router(workspace_api.router)
    return application


def login_as(app, username: str, password: str = "pass-123") -> TestClient:
    client = TestClient(app)
    client.post("/api/auth/register", json={"username": username, "password": password})
    assert client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).status_code == 200
    return client


def assert_unauthorized(response):
    assert response.status_code == 401
    assert response.json()["detail"] == auth_api.UNAUTHORIZED_DETAIL


# --- 4.1 请求模型不再携带归属者 ---


def test_requests_no_longer_accept_user_id():
    assert "user_id" not in ChatRequest.model_fields
    assert "user_id" not in SessionCreateRequest.model_fields

    # 多余的 user_id 被忽略，模型上不出现该字段
    request = ChatRequest(message="hi", user_id="user:bob")

    assert not hasattr(request, "user_id")
    assert request.message == "hi"


# --- 4.2 会话接口 ---


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/sessions", None),
        ("post", "/api/sessions", None),
        ("get", "/api/sessions/session-1", None),
        ("get", "/api/sessions/session-1/messages", None),
    ],
)
def test_session_routes_require_login(app, method, path, body):
    client = TestClient(app)

    response = getattr(client, method)(path, **({"json": body} if body else {}))

    assert_unauthorized(response)


def test_logged_in_user_only_sees_own_sessions(app, session_service):
    session_service.seed(ALICE_ID, "alice-1", ("user", "我是 alice"))
    session_service.seed(BOB_ID, "bob-1", ("user", "我是 bob"))
    alice = login_as(app, "alice")
    bob = login_as(app, "bob")

    alice_list = alice.get("/api/sessions").json()["sessions"]
    bob_list = bob.get("/api/sessions").json()["sessions"]

    assert [item["session_id"] for item in alice_list] == ["alice-1"]
    assert [item["session_id"] for item in bob_list] == ["bob-1"]


def test_anonymous_sessions_are_not_listed(app, session_service):
    """认证改造前落盘的 web-user 会话不出现在任何用户的列表里。"""
    session_service.seed("web-user", "legacy-1", ("user", "旧会话"))
    alice = login_as(app, "alice")

    assert alice.get("/api/sessions").json()["sessions"] == []


def test_other_users_session_is_treated_as_missing(app, session_service):
    session_service.seed(BOB_ID, "bob-1", ("user", "我是 bob"))
    alice = login_as(app, "alice")

    messages = alice.get("/api/sessions/bob-1/messages")
    exists = alice.get("/api/sessions/bob-1")

    assert messages.status_code == 404
    assert exists.status_code == 404
    assert "不存在" in messages.json()["detail"]
    assert any("\u4e00" <= char <= "\u9fff" for char in messages.json()["detail"])


def test_own_session_is_readable_with_prefixed_owner(app, session_service):
    session_service.seed(ALICE_ID, "alice-1", ("user", "我是 alice"), ("assistant", "好的"))
    alice = login_as(app, "alice")

    response = alice.get("/api/sessions/alice-1/messages")

    assert response.status_code == 200
    assert response.json()["user_id"] == ALICE_ID
    assert response.json()["messages"] == [
        {"role": "user", "text": "我是 alice"},
        {"role": "assistant", "text": "好的"},
    ]


def test_client_supplied_owner_is_ignored(app, session_service):
    alice = login_as(app, "alice")

    created = alice.post("/api/sessions", json={"user_id": BOB_ID})
    listed = alice.get("/api/sessions", params={"user_id": BOB_ID})

    assert created.status_code == 200
    assert created.json()["user_id"] == ALICE_ID
    assert session_service.created == [(ALICE_ID, created.json()["session_id"])]
    assert [item["session_id"] for item in listed.json()["sessions"]] == [
        created.json()["session_id"]
    ]


# --- 4.3 对话接口 ---


def test_chat_requires_login_without_side_effects(app, session_service, runner):
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "写个单例"})

    assert_unauthorized(response)
    assert session_service.created == []
    assert runner.calls == []


def test_chat_uses_the_logged_in_identity(app, session_service, runner):
    alice = login_as(app, "alice")

    response = alice.post("/api/chat", json={"message": "写个单例"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert runner.calls[0]["user_id"] == ALICE_ID
    assert session_service.created[0][0] == ALICE_ID
    assert '"type":"done"' in response.text


def test_chat_on_other_users_session_is_rejected(app, session_service, runner):
    session_service.seed(BOB_ID, "bob-1", ("user", "我是 bob"))
    alice = login_as(app, "alice")

    response = alice.post("/api/chat", json={"message": "继续说", "session_id": "bob-1"})

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]
    assert runner.calls == []


# --- 4.4 打包下载接口 ---


def test_download_requires_login(app):
    client = TestClient(app)

    assert_unauthorized(client.get("/api/workspace/download", params={"session_id": "x"}))


def test_download_own_session_succeeds(app, session_service):
    session_service.seed(ALICE_ID, "alice-1", ("user", "生成一个项目"))
    workspace.write_file("alice-1", "main.py", "print(1)")
    alice = login_as(app, "alice")

    response = alice.get("/api/workspace/download", params={"session_id": "alice-1"})

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["main.py"]


def test_download_other_users_session_is_treated_as_missing(app, session_service):
    session_service.seed(BOB_ID, "bob-1", ("user", "我是 bob"))
    workspace.write_file("bob-1", "secret.py", "print('bob')")
    alice = login_as(app, "alice")

    response = alice.get("/api/workspace/download", params={"session_id": "bob-1"})

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_download_unknown_session_reports_missing(app):
    alice = login_as(app, "alice")

    response = alice.get("/api/workspace/download", params={"session_id": "nope"})

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_download_ignores_client_supplied_owner(app, session_service):
    session_service.seed(BOB_ID, "bob-1", ("user", "我是 bob"))
    workspace.write_file("bob-1", "secret.py", "print('bob')")
    alice = login_as(app, "alice")

    response = alice.get(
        "/api/workspace/download", params={"session_id": "bob-1", "user_id": BOB_ID}
    )

    assert response.status_code == 404