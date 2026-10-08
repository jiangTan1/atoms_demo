"""会话沙箱服务的单元测试。

覆盖沙箱隔离、路径安全（绝对路径 / `..` / 符号链接）、配额限制、
读写列目录删除四类操作与打包（见 specs/file-workspace/spec.md）。

沙箱根目录用 monkeypatch 指向临时目录，避免污染项目 data/。
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT, Settings, load_settings
from app.services import workspace

BASE_ENV = {
    "LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "LLM_MODEL": "glm-4.5-flash",
    "LLM_API_KEY": "sk-test-1234567890",
    "SESSION_BACKEND": "memory",
}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把 WORKSPACE_ROOT 指向临时目录，返回该根目录。"""
    root = tmp_path / "workspace"
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", root)
    return root


def make_settings(**overrides) -> Settings:
    env = {**BASE_ENV, **{key: str(value) for key, value in overrides.items()}}
    return load_settings(env)


def try_symlink(link: Path, target: Path) -> bool:
    """创建符号链接；当前环境不允许时返回 False，由用例跳过。"""
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError):
        return False
    return True


# --- 2.1 沙箱目录推导与隔离 ---


def test_workspace_root_sits_under_project_data_dir():
    assert workspace.WORKSPACE_ROOT == PROJECT_ROOT / "data" / "workspace"
    assert workspace.WORKSPACE_ROOT.is_relative_to(PROJECT_ROOT / "data")


def test_each_session_gets_its_own_directory(sandbox):
    first = workspace.workspace_dir("session-a")
    second = workspace.workspace_dir("session-b")

    assert first != second
    assert first.is_relative_to(sandbox)
    assert second.is_relative_to(sandbox)


def test_sessions_do_not_share_files(sandbox):
    workspace.write_file("session-a", "src/main.py", "print('a')")
    workspace.write_file("session-b", "src/main.py", "print('b')")

    assert workspace.read_file("session-a", "src/main.py") == "print('a')"
    assert workspace.read_file("session-b", "src/main.py") == "print('b')"


# --- 2.2 路径安全 ---


def test_absolute_path_is_rejected(sandbox):
    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.write_file("session-a", "/etc/passwd", "x")

    assert "绝对路径" in str(excinfo.value)


def test_parent_traversal_is_rejected(sandbox):
    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.write_file("session-a", "../outside.txt", "x")

    assert "跳出" in str(excinfo.value)


def test_symlink_escape_is_rejected(sandbox, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    base = workspace.workspace_dir("session-a")
    base.mkdir(parents=True, exist_ok=True)
    if not try_symlink(base / "link", outside):
        pytest.skip("当前环境不允许创建符号链接")

    with pytest.raises(workspace.WorkspaceError):
        workspace.read_file("session-a", "link/secret.txt")

    assert (outside / "secret.txt").read_text(encoding="utf-8") == "secret"


def test_relative_path_inside_sandbox_works(sandbox):
    relative, size = workspace.write_file("session-a", "src/main.py", "print(1)")

    assert relative == "src/main.py"
    assert size == len("print(1)")


# --- 2.3 写入与配额 ---


def test_write_creates_parent_directories(sandbox):
    relative, size = workspace.write_file("session-a", "app/api/routes.py", "x = 1")

    assert relative == "app/api/routes.py"
    assert size == 5
    assert (sandbox / "session-a" / "app" / "api" / "routes.py").is_file()


def test_write_overwrites_without_leaving_copies(sandbox):
    workspace.write_file("session-a", "main.py", "old")
    workspace.write_file("session-a", "main.py", "new content")

    assert workspace.read_file("session-a", "main.py") == "new content"
    assert workspace.list_files("session-a") == ["main.py"]


def test_write_empty_content_creates_empty_file(sandbox):
    relative, size = workspace.write_file("session-a", "empty.py", "")

    assert size == 0
    assert workspace.read_file("session-a", relative) == ""


def test_single_file_quota_is_enforced_and_keeps_original(sandbox):
    settings = make_settings(WORKSPACE_MAX_FILE_BYTES=10)
    workspace.write_file("session-a", "main.py", "12345", settings=settings)

    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.write_file("session-a", "main.py", "x" * 11, settings=settings)

    assert "单文件上限" in str(excinfo.value)
    assert workspace.read_file("session-a", "main.py", settings=settings) == "12345"


def test_file_count_quota_is_enforced(sandbox):
    settings = make_settings(WORKSPACE_MAX_FILES=1)
    workspace.write_file("session-a", "a.py", "1", settings=settings)

    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.write_file("session-a", "b.py", "2", settings=settings)

    assert "文件数" in str(excinfo.value)
    assert workspace.list_files("session-a") == ["a.py"]


def test_total_bytes_quota_is_enforced(sandbox):
    settings = make_settings(WORKSPACE_MAX_TOTAL_BYTES=10)
    workspace.write_file("session-a", "a.py", "12345", settings=settings)

    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.write_file("session-a", "b.py", "123456", settings=settings)

    assert "总占用" in str(excinfo.value)


def test_overwrite_is_not_counted_as_new_file(sandbox):
    settings = make_settings(WORKSPACE_MAX_FILES=1)
    workspace.write_file("session-a", "a.py", "1", settings=settings)

    workspace.write_file("session-a", "a.py", "22", settings=settings)

    assert workspace.read_file("session-a", "a.py", settings=settings) == "22"


# --- 2.4 读取与列目录 ---


def test_read_returns_text_content(sandbox):
    workspace.write_file("session-a", "readme.md", "# 标题")

    assert workspace.read_file("session-a", "readme.md") == "# 标题"


def test_read_over_limit_is_rejected(sandbox):
    # 先用默认配额写入，再用收紧的读取上限去读，模拟后续调小配额的情形
    workspace.write_file("session-a", "big.py", "12345")
    settings = make_settings(WORKSPACE_MAX_FILE_BYTES=4)

    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.read_file("session-a", "big.py", settings=settings)

    assert "读取被拒绝" in str(excinfo.value)


def test_list_empty_sandbox_returns_empty_list(sandbox):
    assert workspace.list_files("session-empty") == []


def test_list_returns_all_relative_paths(sandbox):
    workspace.write_file("session-a", "b.py", "b")
    workspace.write_file("session-a", "src/a.py", "a")

    assert workspace.list_files("session-a") == ["b.py", "src/a.py"]


# --- 2.5 删除 ---


def test_delete_removes_file(sandbox):
    workspace.write_file("session-a", "tmp.py", "x")

    assert workspace.delete_file("session-a", "tmp.py") == "tmp.py"
    assert workspace.list_files("session-a") == []


def test_delete_missing_file_returns_readable_failure(sandbox):
    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.delete_file("session-a", "ghost.py")

    assert "不存在" in str(excinfo.value)


def test_delete_directory_is_rejected_and_content_survives(sandbox):
    workspace.write_file("session-a", "pkg/mod.py", "x")

    with pytest.raises(workspace.WorkspaceError) as excinfo:
        workspace.delete_file("session-a", "pkg")

    assert "目录" in str(excinfo.value)
    assert workspace.read_file("session-a", "pkg/mod.py") == "x"


# --- 2.6 打包 ---


def test_zip_preserves_structure_and_content(sandbox):
    workspace.write_file("session-a", "main.py", "print(1)")
    workspace.write_file("session-a", "src/util/helper.py", "def f(): pass")

    data = workspace.zip_workspace("session-a")
    assert data is not None

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sorted(archive.namelist()) == ["main.py", "src/util/helper.py"]
        assert archive.read("main.py").decode("utf-8") == "print(1)"
        assert archive.read("src/util/helper.py").decode("utf-8") == "def f(): pass"


def test_zip_empty_sandbox_returns_none(sandbox):
    assert workspace.zip_workspace("session-empty") is None


def test_zip_contains_only_requested_session(sandbox):
    workspace.write_file("session-a", "a.py", "a")
    workspace.write_file("session-b", "b.py", "b")

    data = workspace.zip_workspace("session-a")
    assert data is not None

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == ["a.py"]


# --- 2.7 应用入口定位（见 specs/file-workspace/spec.md）---


def test_entry_path_finds_index_html(sandbox):
    workspace.write_file("session-a", "index.html", "<h1>hi</h1>")

    entry = workspace.entry_path("session-a")

    assert entry is not None
    assert entry.name == "index.html"
    assert entry.read_text(encoding="utf-8") == "<h1>hi</h1>"


def test_entry_path_returns_none_without_entry(sandbox):
    workspace.write_file("session-a", "main.py", "print(1)")

    assert workspace.entry_path("session-a") is None


def test_entry_path_returns_none_for_empty_sandbox(sandbox):
    assert workspace.entry_path("session-empty") is None


def test_entry_path_ignores_symlink_escaping_the_sandbox(sandbox, tmp_path):
    outside = tmp_path / "outside-index.html"
    outside.write_text("secret", encoding="utf-8")

    base = workspace.workspace_dir("session-a")
    base.mkdir(parents=True, exist_ok=True)
    if not try_symlink(base / "index.html", outside):
        pytest.skip("当前环境不允许创建符号链接")

    assert workspace.entry_path("session-a") is None


# --- 2.8 静态资源按路径取用（见 specs/file-workspace/spec.md）---


def test_read_asset_returns_entry_page_and_content_type(sandbox):
    workspace.write_file("session-a", "index.html", "<!doctype html><h1>hi</h1>")

    content, content_type = workspace.read_asset("session-a", "index.html")

    assert content.decode("utf-8") == "<!doctype html><h1>hi</h1>"
    assert content_type.startswith("text/html")


def test_read_asset_serves_nested_style_and_script(sandbox):
    workspace.write_file("session-a", "assets/style.css", "body{color:red}")
    workspace.write_file("session-a", "src/app.js", "console.log(1)")

    css, css_type = workspace.read_asset("session-a", "assets/style.css")
    js, js_type = workspace.read_asset("session-a", "src/app.js")

    assert css.decode("utf-8") == "body{color:red}"
    assert css_type.startswith("text/css")
    assert js.decode("utf-8") == "console.log(1)"
    assert js_type.startswith("text/javascript")


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside.txt", "assets/../../x.txt"])
def test_read_asset_rejects_escaping_paths(sandbox, path):
    with pytest.raises(workspace.WorkspaceError):
        workspace.read_asset("session-a", path)


def test_read_asset_rejects_symlink_escape(sandbox, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    base = workspace.workspace_dir("session-a")
    base.mkdir(parents=True, exist_ok=True)
    if not try_symlink(base / "link", outside):
        pytest.skip("当前环境不允许创建符号链接")

    with pytest.raises(workspace.WorkspaceError):
        workspace.read_asset("session-a", "link/secret.txt")


@pytest.mark.parametrize("path", [".env", ".git/config", "assets/.hidden.js"])
def test_read_asset_rejects_hidden_files(sandbox, path):
    workspace.write_file("session-a", path, "secret")

    with pytest.raises(workspace.WorkspaceError):
        workspace.read_asset("session-a", path)


# --- 2.9 快照与恢复（见 specs/file-workspace/spec.md）---


def test_snapshot_is_decoupled_from_later_changes(sandbox, tmp_path):
    workspace.write_file("session-a", "index.html", "v1")
    snap = tmp_path / "snap" / "0001"
    workspace.snapshot("session-a", snap)

    workspace.write_file("session-a", "index.html", "v2")

    assert (snap / "index.html").read_text(encoding="utf-8") == "v1"
    assert workspace.read_file("session-a", "index.html") == "v2"


def test_restore_rebuilds_sandbox_exactly(sandbox, tmp_path):
    workspace.write_file("session-a", "index.html", "v1")
    workspace.write_file("session-a", "keep.js", "keep")
    snap = tmp_path / "snap" / "0001"
    workspace.snapshot("session-a", snap)

    workspace.delete_file("session-a", "keep.js")
    workspace.write_file("session-a", "extra.js", "extra")

    workspace.restore("session-a", snap)

    assert sorted(workspace.list_files("session-a")) == ["index.html", "keep.js"]
    assert workspace.read_file("session-a", "index.html") == "v1"
    assert workspace.read_file("session-a", "keep.js") == "keep"


def test_restore_keeps_pre_restore_content(sandbox, tmp_path):
    workspace.write_file("session-a", "index.html", "v1")
    snap = tmp_path / "snap" / "0001"
    workspace.snapshot("session-a", snap)
    workspace.write_file("session-a", "index.html", "v2")

    preserved = tmp_path / "snap" / "0002"
    workspace.restore("session-a", snap, keep=preserved)

    assert workspace.read_file("session-a", "index.html") == "v1"
    assert (preserved / "index.html").read_text(encoding="utf-8") == "v2"


def test_snapshot_only_touches_its_own_session(sandbox, tmp_path):
    workspace.write_file("session-a", "a.html", "a")
    workspace.write_file("session-b", "b.html", "b")
    snap = tmp_path / "snap" / "0001"

    workspace.snapshot("session-a", snap)
    workspace.restore("session-a", snap)

    assert workspace.list_files("session-b") == ["b.html"]