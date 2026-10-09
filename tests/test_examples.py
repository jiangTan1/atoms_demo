"""预置示例应用与「从模板初始化沙箱」的单元测试。

覆盖三层：workspace 的模板复制（配额 / 清理 / 会话隔离）、examples 服务的清单读取与
标识校验、以及 GET /api/examples 与 POST /api/examples/apply 两条接口
（见 specs/example-apps/spec.md 与 specs/file-workspace/spec.md）。

模板根目录与沙箱根目录都用 monkeypatch 指向临时目录，避免依赖发布内容、也不污染 data/。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api import examples as examples_api
from app.config import Settings, load_settings
from app.services import accounts
from app.services import examples as examples_service
from app.services import workspace
from app.services.accounts import AccountService

BASE_ENV = {
    "LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "LLM_MODEL": "glm-4.5-flash",
    "LLM_API_KEY": "sk-test-1234567890",
    "SESSION_BACKEND": "memory",
}

MANIFEST = {
    "examples": [
        {"id": "demo", "name": "演示应用", "description": "一句话描述"},
    ]
}


def make_settings(**overrides) -> Settings:
    env = {**BASE_ENV, **{key: str(value) for key, value in overrides.items()}}
    return load_settings(env)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把沙箱根目录指向临时目录。"""
    root = tmp_path / "workspace"
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", root)
    return root


@pytest.fixture
def templates(tmp_path):
    """自建模板根目录：一个含嵌套资源的示例 + 清单。"""
    root = tmp_path / "templates"
    (root / "demo" / "assets").mkdir(parents=True)
    (root / "demo" / "index.html").write_text("<!doctype html><h1>demo</h1>", encoding="utf-8")
    (root / "demo" / "assets" / "style.css").write_text("body{color:red}", encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(MANIFEST, ensure_ascii=False), encoding="utf-8"
    )
    return root


# --- workspace：从模板初始化沙箱 ---


def test_init_from_template_preserves_nested_structure(sandbox, templates):
    written = workspace.init_from_template("s-1", templates / "demo")

    assert sorted(written) == ["assets/style.css", "index.html"]
    assert workspace.read_file("s-1", "assets/style.css") == "body{color:red}"
    assert workspace.entry_path("s-1") is not None


def test_init_from_template_merges_into_existing_sandbox(sandbox, templates):
    """沙箱原先已有内容时只增补模板文件，不整体替换。"""
    workspace.write_file("s-1", "notes.md", "写在前面的内容")

    workspace.init_from_template("s-1", templates / "demo")

    assert workspace.read_file("s-1", "notes.md") == "写在前面的内容"
    assert sorted(workspace.list_files("s-1")) == ["assets/style.css", "index.html", "notes.md"]


def test_init_from_template_rejects_missing_directory(sandbox, tmp_path):
    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.init_from_template("s-1", tmp_path / "nope")

    assert "模板目录不存在" in str(excinfo.value)


def test_init_from_template_rejects_empty_directory(sandbox, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.init_from_template("s-1", empty)

    assert "没有任何文件" in str(excinfo.value)


def test_init_from_template_rejects_oversized_file_without_writing(sandbox, templates):
    settings = make_settings(WORKSPACE_MAX_FILE_BYTES=4)

    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.init_from_template("s-1", templates / "demo", settings)

    assert "单文件上限" in str(excinfo.value)
    # 配额预检整体拒绝，不留下半初始化沙箱
    assert workspace.list_files("s-1") == []


def test_init_from_template_rejects_file_count_over_quota(sandbox, templates):
    settings = make_settings(WORKSPACE_MAX_FILES=1)

    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.init_from_template("s-1", templates / "demo", settings)

    assert "文件数" in str(excinfo.value)
    assert workspace.list_files("s-1") == []


def test_init_from_template_rejects_total_bytes_over_quota(sandbox, templates):
    settings = make_settings(WORKSPACE_MAX_TOTAL_BYTES=10)

    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.init_from_template("s-1", templates / "demo", settings)

    assert "总占用" in str(excinfo.value)
    assert workspace.list_files("s-1") == []


def test_init_from_template_only_touches_its_own_session(sandbox, templates):
    workspace.write_file("s-2", "keep.txt", "keep")

    workspace.init_from_template("s-1", templates / "demo")

    assert workspace.list_files("s-2") == ["keep.txt"]


# --- examples 服务：清单读取与标识校验 ---


def test_load_examples_reads_manifest(templates):
    examples = examples_service.load_examples(templates)

    assert [(item.id, item.name, item.description) for item in examples] == [
        ("demo", "演示应用", "一句话描述")
    ]


def test_bundled_examples_are_usable():
    """发布内容自检：清单可解析，且每个示例都有可预览的入口文件。"""
    examples = examples_service.load_examples()

    assert 3 <= len(examples) <= 4
    for item in examples:
        assert item.name and item.description
        assert (examples_service.template_dir(item.id) / "index.html").is_file()


def test_missing_manifest_reports_readable_error(tmp_path):
    with pytest.raises(examples_service.ExampleError) as excinfo:
        examples_service.load_examples(tmp_path)

    assert "示例清单缺失" in str(excinfo.value)


def test_unparsable_manifest_reports_readable_error(tmp_path):
    (tmp_path / "manifest.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(examples_service.ExampleError) as excinfo:
        examples_service.load_examples(tmp_path)

    assert "无法解析" in str(excinfo.value)


def test_manifest_without_examples_array_is_rejected(tmp_path):
    (tmp_path / "manifest.json").write_text('{"items": []}', encoding="utf-8")

    with pytest.raises(examples_service.ExampleError) as excinfo:
        examples_service.load_examples(tmp_path)

    assert "examples" in str(excinfo.value)


def test_manifest_entry_without_id_is_rejected(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"examples": [{"name": "缺标识"}]}, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(examples_service.ExampleError) as excinfo:
        examples_service.load_examples(tmp_path)

    assert "id" in str(excinfo.value)


def test_find_example_returns_none_for_unknown_id(templates):
    assert examples_service.find_example("ghost", templates) is None
    assert examples_service.find_example("demo", templates).name == "演示应用"


def test_template_dir_rejects_escaping_id(templates):
    with pytest.raises(examples_service.ExampleError):
        examples_service.template_dir("../outside", templates)


def test_apply_to_session_copies_files(sandbox, templates):
    written = examples_service.apply_to_session("s-1", "demo", root=templates)

    assert sorted(written) == ["assets/style.css", "index.html"]
    assert workspace.entry_path("s-1") is not None


def test_apply_to_session_rejects_unknown_example(sandbox, templates):
    with pytest.raises(examples_service.ExampleError) as excinfo:
        examples_service.apply_to_session("s-1", "ghost", root=templates)

    assert "不存在" in str(excinfo.value)
    assert workspace.list_files("s-1") == []


def test_apply_to_session_reports_missing_template_directory(sandbox, templates):
    """清单登记了示例但目录缺失时，给出可读错误且不创建半初始化沙箱。"""
    import shutil

    shutil.rmtree(templates / "demo")

    with pytest.raises(examples_service.ExampleError) as excinfo:
        examples_service.apply_to_session("s-1", "demo", root=templates)

    assert "模板目录不存在" in str(excinfo.value)
    assert workspace.list_files("s-1") == []


# --- 接口层：列表与选用 ---


class FakeSessionService:
    """只保留创建 / 删除的假会话服务。"""

    def __init__(self):
        self.store: dict[tuple[str, str], SimpleNamespace] = {}
        self.deleted: list[tuple[str, str]] = []

    async def create_session(self, *, app_name, user_id, session_id=None):
        sid = session_id or f"session-{len(self.store) + 1}"
        session = SimpleNamespace(id=sid, events=[], app_name=app_name, user_id=user_id)
        self.store[(user_id, sid)] = session
        return session

    async def delete_session(self, *, app_name, user_id, session_id):
        self.deleted.append((user_id, session_id))
        self.store.pop((user_id, session_id), None)

    async def get_session(self, *, app_name, user_id, session_id):
        return self.store.get((user_id, session_id))

    async def list_sessions(self, *, app_name, user_id):
        return SimpleNamespace(
            sessions=[session for (uid, _), session in self.store.items() if uid == user_id]
        )


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(accounts, "_HASH_ITERATIONS", 1000)


@pytest.fixture
def session_service():
    return FakeSessionService()


@pytest.fixture
def app(tmp_path, monkeypatch, templates, session_service):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(workspace, "TEMPLATES_ROOT", templates)

    accounts_service = AccountService(tmp_path / "users.db")
    accounts_service.ensure_admin("root", "root")

    application = FastAPI()
    application.state.settings = make_settings()
    application.state.accounts = accounts_service
    application.state.session_service = session_service
    application.include_router(auth_api.router)
    application.include_router(examples_api.router)
    return application


def login_as(app, username: str, password: str = "pass-123") -> TestClient:
    client = TestClient(app)
    client.post("/api/auth/register", json={"username": username, "password": password})
    assert client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).status_code == 200
    return client


def test_examples_list_requires_login(app):
    response = TestClient(app).get("/api/examples")

    assert response.status_code == 401
    assert response.json()["detail"] == auth_api.UNAUTHORIZED_DETAIL


def test_examples_apply_requires_login(app, session_service):
    response = TestClient(app).post("/api/examples/apply", json={"example_id": "demo"})

    assert response.status_code == 401
    assert session_service.store == {}


def test_examples_list_returns_manifest_items(app):
    alice = login_as(app, "alice")

    response = alice.get("/api/examples")

    assert response.status_code == 200
    assert response.json()["examples"] == [
        {"id": "demo", "name": "演示应用", "description": "一句话描述"}
    ]


def test_examples_apply_creates_session_with_copied_files(app, session_service):
    alice = login_as(app, "alice")

    response = alice.post("/api/examples/apply", json={"example_id": "demo"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["example_id"] == "demo"
    assert "演示应用" in payload["message"]
    # 会话归属当前登录用户，沙箱已写好，可直接预览
    assert (f"user:alice", payload["session_id"]) in session_service.store
    assert workspace.entry_path(payload["session_id"]) is not None
    assert sorted(workspace.list_files(payload["session_id"])) == [
        "assets/style.css",
        "index.html",
    ]


def test_examples_apply_unknown_id_is_404(app, session_service):
    alice = login_as(app, "alice")

    response = alice.post("/api/examples/apply", json={"example_id": "ghost"})

    assert response.status_code == 404
    assert "ghost" in response.json()["detail"]
    # 未知示例不应创建任何会话
    assert session_service.store == {}


def test_examples_apply_rolls_back_session_when_copy_fails(
    app, session_service, monkeypatch
):
    """复制失败时回退：删除刚创建的空会话并清掉沙箱，不留残缺状态。"""
    alice = login_as(app, "alice")

    def explode(*args, **kwargs):
        raise examples_service.ExampleError("磁盘写入失败")

    monkeypatch.setattr(examples_api.examples_service, "apply_to_session", explode)

    response = alice.post("/api/examples/apply", json={"example_id": "demo"})

    assert response.status_code == 500
    assert "磁盘写入失败" in response.json()["detail"]
    assert session_service.store == {}
    assert session_service.deleted == [("user:alice", "session-1")]