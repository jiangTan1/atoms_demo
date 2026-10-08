"""分享接口与免登录分享预览的测试。

覆盖创建/列出/撤销与创建者归属（见 specs/app-sharing/spec.md 的「分享的创建者归属与撤销」），
免登录只读预览、撤销后失效、随机 token 不可枚举（「生成公开只读分享链接」「分享链接不可枚举」），
分享页不暴露会话信息、不能用于下载（「分享为只读」），以及分享预览的隔离与安全头（「分享的运行隔离」）。

沙箱、版本与分享库都落在临时目录。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api import shares as shares_api
from app.api import versions as versions_api
from app.api import workspace as workspace_api
from app.config import load_settings
from app.services import accounts, versions, workspace
from app.services.accounts import AccountService
from app.services.shares import ShareService

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
    application.state.shares = ShareService(tmp_path / "shares.db")
    application.include_router(auth_api.router)
    application.include_router(versions_api.router)
    application.include_router(workspace_api.router)
    application.include_router(shares_api.router)
    application.include_router(shares_api.share_router)
    return application


def login_as(app, username: str = "alice") -> TestClient:
    client = TestClient(app)
    client.post("/api/auth/register", json={"username": username, "password": "pass-123"})
    assert client.post(
        "/api/auth/login", json={"username": username, "password": "pass-123"}
    ).status_code == 200
    return client


def make_version(session_id: str = "alice-1", content: str = "<h1>A</h1>") -> str:
    """写一个含样式的小应用并生成一个版本，返回版本标识。"""
    workspace.write_file(
        session_id,
        "index.html",
        '<link rel="stylesheet" href="style.css"><h1>俄罗斯方块</h1>',
        SETTINGS,
    )
    workspace.write_file(session_id, "style.css", f"h1 {{ color: red; }} /* {content} */", SETTINGS)
    record = versions.snapshot_if_changed(session_id, SETTINGS)
    assert record is not None
    return record["version_id"]


def create_share(client, session_id: str = "alice-1", version_id: str = "0001") -> dict:
    response = client.post(
        f"/api/sessions/{session_id}/shares", json={"version_id": version_id}
    )
    assert response.status_code == 200, response.text
    return response.json()["share"]


# --- 5.2 分享接口 ---


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/sessions/alice-1/shares", None),
        ("post", "/api/sessions/alice-1/shares", {"version_id": "0001"}),
        ("delete", "/api/shares/some-token", None),
    ],
)
def test_share_routes_require_login(app, method, path, payload):
    client = TestClient(app)

    response = getattr(client, method)(path, **({"json": payload} if payload else {}))

    assert response.status_code == 401
    assert response.json()["detail"] == auth_api.UNAUTHORIZED_DETAIL


def test_create_share_for_own_version(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    version_id = make_version("alice-1")
    alice = login_as(app)

    share = create_share(alice, "alice-1", version_id)

    assert share["version_id"] == version_id
    assert share["url"] == f"/share/{share['token']}/"
    assert len(share["token"]) >= 32


def test_create_share_on_other_users_session_is_rejected(app, session_service):
    session_service.seed(BOB_ID, "bob-1")
    version_id = make_version("bob-1")
    alice = login_as(app)

    response = alice.post(
        "/api/sessions/bob-1/shares", json={"version_id": version_id}
    )

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]
    assert alice.get("/api/sessions/bob-1/shares").status_code == 404


def test_create_share_for_a_missing_version_is_rejected(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    make_version("alice-1")
    alice = login_as(app)

    response = alice.post(
        "/api/sessions/alice-1/shares", json={"version_id": "0009"}
    )

    assert response.status_code == 404
    assert "0009" in response.json()["detail"]


def test_list_and_revoke_own_shares(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    version_id = make_version("alice-1")
    alice = login_as(app)
    first = create_share(alice, "alice-1", version_id)
    second = create_share(alice, "alice-1", version_id)

    listed = alice.get("/api/sessions/alice-1/shares").json()["shares"]
    revoked = alice.delete(f"/api/shares/{first['token']}")
    remaining = alice.get("/api/sessions/alice-1/shares").json()["shares"]

    assert [item["token"] for item in listed] == [second["token"], first["token"]]
    assert revoked.status_code == 200
    assert [item["token"] for item in remaining] == [second["token"]]


def test_revoke_only_works_for_the_creator(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    version_id = make_version("alice-1")
    alice = login_as(app)
    share = create_share(alice, "alice-1", version_id)
    bob = login_as(app, "bob")

    response = bob.delete(f"/api/shares/{share['token']}")

    assert response.status_code == 404
    assert alice.get(f"/share/{share['token']}/").status_code == 200


# --- 5.2/5.3 免登录分享预览 ---


def test_share_page_opens_without_login_and_hides_session_info(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    version_id = make_version("alice-1")
    share = create_share(login_as(app), "alice-1", version_id)

    response = TestClient(app).get(f"/share/{share['token']}/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert f"/share/{share['token']}/app/" in response.text
    # 只读分享页不暴露会话标识与版本编号
    assert "alice-1" not in response.text
    assert version_id not in response.text


def test_share_page_uses_a_restricted_sandbox(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    share = create_share(login_as(app), "alice-1", make_version("alice-1"))

    page = TestClient(app).get(f"/share/{share['token']}/").text

    assert "allow-scripts" in page
    assert "allow-same-origin" not in page
    assert "allow-top-navigation" not in page


def test_shared_app_runs_without_login(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    share = create_share(login_as(app), "alice-1", make_version("alice-1"))
    visitor = TestClient(app)

    entry = visitor.get(f"/share/{share['token']}/app/")
    css = visitor.get(f"/share/{share['token']}/app/style.css")

    assert entry.status_code == 200
    assert entry.headers["content-type"].startswith("text/html")
    assert "俄罗斯方块" in entry.text
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")


def test_share_preview_sets_the_same_security_headers(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    share = create_share(login_as(app), "alice-1", make_version("alice-1"))

    response = TestClient(app).get(f"/share/{share['token']}/app/")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "connect-src 'none'" in response.headers["content-security-policy"]


def test_shared_snapshot_does_not_change_with_the_sandbox(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    share = create_share(login_as(app), "alice-1", make_version("alice-1"))
    workspace.write_file("alice-1", "index.html", "<h1>改过了</h1>", SETTINGS)

    entry = TestClient(app).get(f"/share/{share['token']}/app/")

    assert "俄罗斯方块" in entry.text
    assert "改过了" not in entry.text


def test_revoked_share_link_stops_working(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    alice = login_as(app)
    share = create_share(alice, "alice-1", make_version("alice-1"))
    alice.delete(f"/api/shares/{share['token']}")
    visitor = TestClient(app)

    page = visitor.get(f"/share/{share['token']}/")
    entry = visitor.get(f"/share/{share['token']}/app/")

    assert page.status_code == 404
    assert entry.status_code == 404
    assert "分享不存在或已失效" in page.text
    assert "俄罗斯方块" not in entry.text


@pytest.mark.parametrize(
    "path",
    ["/share/not-a-real-token/", "/share/not-a-real-token/app/", "/share/not-a-real-token/app/style.css"],
)
def test_random_token_returns_no_content(app, path):
    response = TestClient(app).get(path)

    assert response.status_code == 404
    assert "分享不存在或已失效" in response.text


def test_share_link_cannot_be_used_to_download(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    share = create_share(login_as(app), "alice-1", make_version("alice-1"))

    response = TestClient(app).get(
        "/api/workspace/download", params={"session_id": "alice-1"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == auth_api.UNAUTHORIZED_DETAIL
    assert share["token"] not in response.text


def test_shared_app_does_not_serve_hidden_files(app, session_service):
    session_service.seed(ALICE_ID, "alice-1")
    workspace.write_file("alice-1", ".env", "SECRET=1", SETTINGS)
    share = create_share(login_as(app), "alice-1", make_version("alice-1"))

    response = TestClient(app).get(f"/share/{share['token']}/app/.env")

    assert response.status_code == 404
    assert "SECRET=1" not in response.text