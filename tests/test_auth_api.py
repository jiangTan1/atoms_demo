"""认证接口与鉴权依赖的单元测试。

用只挂 `auth` 路由的最小应用 + 临时账号库，覆盖鉴权依赖的 401、
注册 / 登录 / 退出登录 / 改密 / 当前身份，以及管理员用户管理接口
（见 openspec/changes/add-user-authentication/tasks.md 的第 3 组任务）。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.config import ConfigError
from app.services import accounts
from app.services.accounts import (
    ROLE_ADMIN,
    ROLE_USER,
    SOURCE_SYSTEM,
    AccountService,
)

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root"


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(accounts, "_HASH_ITERATIONS", 1000)


@pytest.fixture
def service(tmp_path):
    instance = AccountService(tmp_path / "users.db")
    instance.ensure_admin(ADMIN_USERNAME, ADMIN_PASSWORD)
    return instance


def make_client(service, *, secure: bool = False) -> TestClient:
    """只挂认证路由的最小应用，避免依赖真实配置与 Runner。"""
    app = FastAPI()
    app.state.settings = SimpleNamespace(auth_cookie_secure=secure)
    app.state.accounts = service
    app.include_router(auth_api.router)
    return TestClient(app)


@pytest.fixture
def client(service):
    return make_client(service)


def register(client, username="alice", password="pass-123"):
    return client.post("/api/auth/register", json={"username": username, "password": password})


def login(client, username="alice", password="pass-123"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def assert_unauthorized(response):
    assert response.status_code == 401
    assert response.json()["detail"] == auth_api.UNAUTHORIZED_DETAIL
    assert any("\u4e00" <= char <= "\u9fff" for char in response.json()["detail"])


# --- 3.1 鉴权依赖 ---


def test_missing_cookie_is_unauthorized(client):
    assert_unauthorized(client.get("/api/auth/me"))


def test_forged_token_is_unauthorized(client):
    client.cookies.set(auth_api.COOKIE_NAME, "forged-token")

    assert_unauthorized(client.get("/api/auth/me"))


def test_expired_token_is_unauthorized(client, service):
    service.register("alice", "pass-123")
    token = service.issue_token("alice")
    with service._transaction() as conn:
        conn.execute(
            "UPDATE login_tokens SET expires_at = ? WHERE token = ?",
            (time.time() - 1, token),
        )
    client.cookies.set(auth_api.COOKIE_NAME, token)

    assert_unauthorized(client.get("/api/auth/me"))


def test_valid_token_returns_identity(client, service):
    service.register("alice", "pass-123")
    token = service.issue_token("alice")
    client.cookies.set(auth_api.COOKIE_NAME, token)

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": ROLE_USER}


# --- 3.2 认证接口 ---


def test_register_then_login_sets_cookie(client):
    assert register(client).status_code == 200

    response = login(client)

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": ROLE_USER}
    cookie = response.headers["set-cookie"].lower()
    assert auth_api.COOKIE_NAME in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "max-age=86400" in cookie
    assert "secure" not in cookie


def test_login_cookie_is_secure_when_configured(service):
    secure_client = make_client(service, secure=True)
    register(secure_client)

    response = login(secure_client)

    assert "secure" in response.headers["set-cookie"].lower()


def test_register_rejects_duplicate_and_short_credentials(client):
    register(client)

    duplicate = register(client)
    short = register(client, "ab", "pass-123")

    assert duplicate.status_code == 400
    assert "已被使用" in duplicate.json()["detail"]
    assert short.status_code == 400
    assert "用户名" in short.json()["detail"]


def test_login_failure_is_uniform_and_sets_no_cookie(client):
    register(client)

    wrong_password = login(client, password="wrong-123")
    unknown_user = login(client, username="nobody")

    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]
    assert "set-cookie" not in wrong_password.headers
    assert "set-cookie" not in unknown_user.headers


def test_logout_invalidates_the_token(client):
    register(client)
    login(client)
    assert client.get("/api/auth/me").status_code == 200

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert_unauthorized(client.get("/api/auth/me"))


def test_change_password_keeps_current_session_and_drops_the_other(service):
    register(make_client(service))
    first = make_client(service)
    second = make_client(service)
    login(first)
    login(second)

    response = second.post(
        "/api/auth/password",
        json={"old_password": "pass-123", "new_password": "new-pass-1"},
    )

    assert response.status_code == 200
    assert second.get("/api/auth/me").status_code == 200
    assert_unauthorized(first.get("/api/auth/me"))
    # 新密码可重新登录
    fresh = make_client(service)
    assert login(fresh, password="new-pass-1").status_code == 200


def test_change_password_rejects_wrong_old_password(client):
    register(client)
    login(client)

    response = client.post(
        "/api/auth/password",
        json={"old_password": "wrong-123", "new_password": "new-pass-1"},
    )

    assert response.status_code == 400
    assert "原密码" in response.json()["detail"]
    assert login(make_client_from(client), password="pass-123").status_code == 200


def make_client_from(client: TestClient) -> TestClient:
    """复用同一个账号库再开一个客户端，用于确认旧密码仍然有效。"""
    return make_client(client.app.state.accounts)


def test_change_password_requires_login(client):
    response = client.post(
        "/api/auth/password",
        json={"old_password": "pass-123", "new_password": "new-pass-1"},
    )

    assert_unauthorized(response)


# --- 3.3 管理员用户管理接口 ---


def admin_client(service):
    instance = make_client(service)
    login(instance, ADMIN_USERNAME, ADMIN_PASSWORD)
    return instance


def test_admin_can_create_reset_and_delete_user(service):
    admin = admin_client(service)

    created = admin.post("/api/auth/users", json={"username": "bob", "password": "pass-123"})
    assert created.status_code == 200
    bob = make_client(service)
    assert login(bob, "bob", "pass-123").status_code == 200

    reset = admin.post("/api/auth/users/bob/password", json={"password": "reset-123"})
    assert reset.status_code == 200
    assert_unauthorized(bob.get("/api/auth/me"))  # 重置后原登录态失效
    assert login(make_client(service), "bob", "reset-123").status_code == 200

    deleted = admin.delete("/api/auth/users/bob")
    assert deleted.status_code == 200
    assert login(make_client(service), "bob", "reset-123").status_code == 401


def test_admin_cannot_delete_root(service):
    admin = admin_client(service)

    response = admin.delete(f"/api/auth/users/{ADMIN_USERNAME}")

    assert response.status_code == 400
    assert "默认管理员" in response.json()["detail"]
    assert service.get_account(ADMIN_USERNAME).source == SOURCE_SYSTEM


def test_ordinary_user_is_rejected_by_admin_endpoints(service):
    register(make_client(service))
    user = make_client(service)
    login(user)

    create = user.post("/api/auth/users", json={"username": "carol", "password": "pass-123"})
    reset = user.post("/api/auth/users/alice/password", json={"password": "reset-123"})
    delete = user.delete("/api/auth/users/alice")

    for response in (create, reset, delete):
        assert response.status_code == 403
        assert response.json()["detail"] == auth_api.PERMISSION_DETAIL
    # 权限不足时不得产生任何账号变更
    assert service.get_account("carol") is None
    assert service.get_account("alice") is not None
    assert login(make_client(service), "alice", "pass-123").status_code == 200


def test_admin_endpoints_require_login(client):
    assert_unauthorized(client.post("/api/auth/users", json={"username": "bob", "password": "pass-123"}))
    assert_unauthorized(client.post("/api/auth/users/bob/password", json={"password": "reset-123"}))
    assert_unauthorized(client.delete("/api/auth/users/bob"))


def test_admin_create_user_reports_missing_target(service):
    admin = admin_client(service)

    response = admin.post("/api/auth/users/nobody/password", json={"password": "reset-123"})

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_admin_role_is_reported_in_identity(service):
    admin = admin_client(service)

    assert admin.get("/api/auth/me").json() == {
        "username": ADMIN_USERNAME,
        "role": ROLE_ADMIN,
    }


# --- 3.4 应用装配 ---


def _stub_runner(monkeypatch, main_module):
    class StubRunnerService:
        """替代真实 Runner，让 lifespan 不必连模型也能跑通。"""

        def __init__(self, settings):
            self.session_service = object()
            self.runner = object()

        async def aclose(self):
            return None

    monkeypatch.setattr(main_module, "RunnerService", StubRunnerService)


def test_app_wires_auth_router_and_initializes_admin(tmp_path, monkeypatch):
    """认证路由应在静态前端之前挂载；启动时用 ADMIN_* 配置创建首个管理员。"""
    from app import main as main_module

    db_path = tmp_path / "users.db"
    monkeypatch.setattr(main_module, "AccountService", lambda: AccountService(db_path))
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(
            auth_cookie_secure=False,
            admin_username=ADMIN_USERNAME,
            admin_password=ADMIN_PASSWORD,
        ),
    )
    _stub_runner(monkeypatch, main_module)

    app = main_module.create_app()
    paths = set(app.openapi()["paths"])
    assert {
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/me",
        "/api/auth/logout",
        "/api/auth/password",
        "/api/auth/users",
        "/api/auth/users/{username}/password",
        "/api/auth/users/{username}",
    } <= paths
    assert getattr(app.routes[-1], "path", None) == ""  # 静态前端仍在最后

    with TestClient(app) as client:
        assert client.get("/api/auth/me").status_code == 401  # lifespan 已执行且无登录态

    assert AccountService(db_path).get_account(ADMIN_USERNAME) is not None


def test_startup_fails_when_the_store_is_empty_and_admin_credentials_are_missing(
    tmp_path, monkeypatch
):
    """账号库为空且未配置 ADMIN_* 时启动失败，并点名缺失的配置项。"""
    from app import main as main_module

    db_path = tmp_path / "users.db"
    monkeypatch.setattr(main_module, "AccountService", lambda: AccountService(db_path))
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(
            auth_cookie_secure=False, admin_username=None, admin_password=None
        ),
    )
    _stub_runner(monkeypatch, main_module)

    app = main_module.create_app()
    with pytest.raises(ConfigError) as excinfo:
        with TestClient(app):
            pass

    assert excinfo.value.key == "ADMIN_USERNAME"