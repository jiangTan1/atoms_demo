"""预览接口的测试。

覆盖入口页面、相对路径资源、缺少入口文件时的提示、会话归属与未登录拒绝
（见 specs/web-app-preview/spec.md 的「沙箱应用预览」「预览资源解析」「预览的访问归属」），
以及安全响应头与隐藏文件/目录拒绝（见「预览运行隔离」）。

沙箱根目录指向临时目录，账号库与会话服务都是临时实例。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api import preview as preview_api
from app.services import accounts, workspace
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

    accounts_service = AccountService(tmp_path / "users.db")
    accounts_service.ensure_admin("root", "root")

    application = FastAPI()
    application.state.settings = SimpleNamespace(auth_cookie_secure=False)
    application.state.accounts = accounts_service
    application.state.session_service = session_service
    application.include_router(auth_api.router)
    application.include_router(preview_api.router)
    return application


def login_as(app, username: str = "alice") -> TestClient:
    client = TestClient(app)
    client.post("/api/auth/register", json={"username": username, "password": "pass-123"})
    assert client.post(
        "/api/auth/login", json={"username": username, "password": "pass-123"}
    ).status_code == 200
    return client


def write_app(session_id: str = "alice-1") -> None:
    """写一个含样式与脚本引用的小应用，用于验证相对路径资源。"""
    workspace.write_file(
        session_id,
        "index.html",
        '<!doctype html><link rel="stylesheet" href="./style.css">'
        '<script src="assets/app.js"></script><h1>俄罗斯方块</h1>',
    )
    workspace.write_file(session_id, "style.css", "h1 { color: red; }")
    workspace.write_file(session_id, "assets/app.js", "console.log('go');")


# --- 4.1 预览接口 ---


def test_preview_requires_login(app):
    response = TestClient(app).get("/preview/alice-1/")

    assert response.status_code == 401
    assert response.json()["detail"] == auth_api.UNAUTHORIZED_DETAIL


def test_preview_returns_the_entry_page(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    write_app()
    alice = login_as(app)

    response = alice.get("/preview/alice-1/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "俄罗斯方块" in response.text


def test_preview_serves_relative_assets(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    write_app()
    alice = login_as(app)

    css = alice.get("/preview/alice-1/style.css")
    script = alice.get("/preview/alice-1/assets/app.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "color: red" in css.text
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert "console.log" in script.text


def test_preview_reports_a_missing_entry_file(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    workspace.write_file("alice-1", "main.py", "print(1)")
    alice = login_as(app)

    response = alice.get("/preview/alice-1/")

    assert response.status_code == 404
    assert "index.html" in response.json()["detail"]


def test_preview_reports_an_empty_sandbox(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    alice = login_as(app)

    response = alice.get("/preview/alice-1/")

    assert response.status_code == 404
    assert "还没有可预览的应用" in response.json()["detail"]


def test_preview_other_users_session_is_treated_as_missing(app, session_service):
    session_service.seed(BOB_ID, "bob-1")
    write_app("bob-1")
    alice = login_as(app)

    response = alice.get("/preview/bob-1/")

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]
    assert "俄罗斯方块" not in response.text


def test_preview_missing_asset_does_not_break_the_page(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    write_app()
    alice = login_as(app)

    page = alice.get("/preview/alice-1/")
    missing = alice.get("/preview/alice-1/nope.png")

    assert page.status_code == 200
    assert missing.status_code == 404


# --- 4.2 安全响应头与隐藏文件 ---


def test_preview_sets_security_headers(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    write_app()
    alice = login_as(app)

    responses = [
        alice.get("/preview/alice-1/"),
        alice.get("/preview/alice-1/style.css"),
    ]

    for response in responses:
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert "connect-src 'none'" in response.headers["content-security-policy"]


def test_preview_rejects_hidden_files(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    write_app()
    workspace.write_file("alice-1", ".env", "SECRET=1")
    workspace.write_file("alice-1", ".git/config", "[core]")
    alice = login_as(app)

    env = alice.get("/preview/alice-1/.env")
    git = alice.get("/preview/alice-1/.git/config")

    assert env.status_code == 404
    assert git.status_code == 404
    assert "SECRET=1" not in env.text


def test_preview_does_not_list_directories(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    write_app()
    alice = login_as(app)

    response = alice.get("/preview/alice-1/assets")

    assert response.status_code == 404
    assert "app.js" not in response.text