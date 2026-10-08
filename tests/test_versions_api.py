"""版本接口的测试。

覆盖未登录拒绝、只能列出与回滚自己的会话、回滚不存在的版本被拒且沙箱不变
（见 specs/app-versions/spec.md）。

沙箱与版本根目录指向临时目录；接口用到的配置由应用的 `state.settings` 提供，
因此不依赖进程环境变量。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api import versions as versions_api
from app.config import load_settings
from app.services import accounts, versions, workspace
from app.services.accounts import AccountService

ALICE_ID = "user:alice"
BOB_ID = "user:bob"

SETTINGS = load_settings(
    {
        "LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
        "LLM_MODEL": "glm-4.5-flash",
        "LLM_API_KEY": "sk-test-1234567890",
        "SESSION_BACKEND": "memory",
    }
)


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(accounts, "_HASH_ITERATIONS", 1000)


class FakeSessionService:
    """只保留归属信息的假会话服务，键为 (user_id, session_id)。"""

    def __init__(self):
        self.store: dict[tuple[str, str], SimpleNamespace] = {}

    async def get_session(self, *, app_name, user_id, session_id):
        return self.store.get((user_id, session_id))

    def seed(self, user_id: str, session_id: str):
        session = SimpleNamespace(id=session_id, events=[], last_update_time=1.0)
        self.store[(user_id, session_id)] = session
        return session


@pytest.fixture
def session_service():
    return FakeSessionService()


@pytest.fixture
def app(tmp_path, monkeypatch, session_service):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(versions, "VERSIONS_ROOT", tmp_path / "versions")

    accounts_service = AccountService(tmp_path / "users.db")
    accounts_service.ensure_admin("root", "root")

    application = FastAPI()
    application.state.settings = SETTINGS
    application.state.accounts = accounts_service
    application.state.session_service = session_service
    application.include_router(auth_api.router)
    application.include_router(versions_api.router)
    return application


def login_as(app, username: str = "alice") -> TestClient:
    client = TestClient(app)
    client.post("/api/auth/register", json={"username": username, "password": "pass-123"})
    assert client.post(
        "/api/auth/login", json={"username": username, "password": "pass-123"}
    ).status_code == 200
    return client


def make_version(session_id: str = "alice-1", content: str = "<h1>A</h1>") -> str:
    """写一个入口文件并生成一个版本，返回版本标识。"""
    workspace.write_file(session_id, "index.html", content, SETTINGS)
    record = versions.snapshot_if_changed(session_id, SETTINGS)
    assert record is not None
    return record["version_id"]


# --- 3.2 版本接口 ---


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/sessions/alice-1/versions"),
        ("post", "/api/sessions/alice-1/versions/0001/rollback"),
    ],
)
def test_version_routes_require_login(app, method, path):
    client = TestClient(app)

    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json()["detail"] == auth_api.UNAUTHORIZED_DETAIL


def test_list_versions_of_own_session(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    make_version("alice-1", "A")
    make_version("alice-1", "B")
    alice = login_as(app)

    response = alice.get("/api/sessions/alice-1/versions")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "alice-1"
    assert [item["version_id"] for item in body["versions"]] == ["0002", "0001"]


def test_list_versions_of_a_session_without_versions(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    alice = login_as(app)

    response = alice.get("/api/sessions/alice-1/versions")

    assert response.status_code == 200
    assert response.json()["versions"] == []


def test_listing_other_users_session_is_rejected(app, session_service):
    session_service.seed(BOB_ID, "bob-1")
    make_version("bob-1")
    alice = login_as(app)

    response = alice.get("/api/sessions/bob-1/versions")

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_rollback_restores_the_target_version(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    make_version("alice-1", "A")
    make_version("alice-1", "B")
    alice = login_as(app)

    response = alice.post("/api/sessions/alice-1/versions/0001/rollback")

    assert response.status_code == 200
    body = response.json()
    assert body["version_id"] == "0001"
    assert body["preserved_version_id"] == "0003"
    assert body["message"]
    assert workspace.read_file("alice-1", "index.html", SETTINGS) == "A"


def test_rollback_of_a_missing_version_keeps_the_sandbox(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    make_version("alice-1", "A")
    alice = login_as(app)

    response = alice.post("/api/sessions/alice-1/versions/0009/rollback")

    assert response.status_code == 404
    assert "0009" in response.json()["detail"]
    assert workspace.read_file("alice-1", "index.html", SETTINGS) == "A"


def test_rollback_of_other_users_session_is_rejected(app, session_service):
    session_service.seed(BOB_ID, "bob-1")
    make_version("bob-1", "A")
    alice = login_as(app)

    response = alice.post("/api/sessions/bob-1/versions/0001/rollback")

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]
    assert workspace.read_file("bob-1", "index.html", SETTINGS) == "A"