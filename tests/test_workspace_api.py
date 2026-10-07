"""打包下载接口的单元测试。

覆盖「有文件」「沙箱为空」「会话不存在」三种情形（见 specs/file-workspace/spec.md
的「项目打包下载」），用假请求代替真实应用，沙箱根目录指向临时目录；
并确认查询会话时使用的归属标识取自登录态。
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import workspace as api_workspace
from app.services import workspace


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", root)
    return root


def make_user(username="alice"):
    """直连路由函数时替代鉴权依赖的当前身份。"""
    return SimpleNamespace(
        username=username, role="user", token="t-1", session_user_id=f"user:{username}"
    )


def make_request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_service=object())))


def patch_session(monkeypatch, *, exists: bool):
    seen = {}

    async def fake_get_session(session_service, *, user_id, session_id):
        seen["user_id"] = user_id
        return SimpleNamespace(id=session_id) if exists else None

    monkeypatch.setattr(api_workspace, "get_session", fake_get_session)
    return seen


def download(session_id: str = "session-a", user=None):
    return asyncio.run(
        api_workspace.download_workspace(
            make_request(), session_id=session_id, user=user or make_user()
        )
    )


def test_download_returns_zip_with_structure(monkeypatch, sandbox):
    patch_session(monkeypatch, exists=True)
    workspace.write_file("abcdef1234567890", "main.py", "print(1)")
    workspace.write_file("abcdef1234567890", "src/util.py", "x = 1")

    response = download("abcdef1234567890")

    assert response.media_type == "application/zip"
    assert "workspace-abcdef12.zip" in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert sorted(archive.namelist()) == ["main.py", "src/util.py"]
        assert archive.read("src/util.py").decode("utf-8") == "x = 1"


def test_download_uses_the_logged_in_identity(monkeypatch, sandbox):
    seen = patch_session(monkeypatch, exists=True)
    workspace.write_file("session-a", "a.py", "a")

    download("session-a", user=make_user("bob"))

    assert seen["user_id"] == "user:bob"


def test_download_empty_sandbox_reports_no_content(monkeypatch, sandbox):
    patch_session(monkeypatch, exists=True)

    with pytest.raises(HTTPException) as excinfo:
        download()

    assert excinfo.value.status_code == 404
    assert "没有生成任何文件" in excinfo.value.detail


def test_download_unknown_session_reports_404(monkeypatch, sandbox):
    patch_session(monkeypatch, exists=False)

    with pytest.raises(HTTPException) as excinfo:
        download("missing")

    assert excinfo.value.status_code == 404
    assert "不存在" in excinfo.value.detail


def test_download_zip_contains_only_this_session(monkeypatch, sandbox):
    patch_session(monkeypatch, exists=True)
    workspace.write_file("session-a", "a.py", "a")
    workspace.write_file("session-b", "b.py", "b")

    response = download("session-a")

    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert archive.namelist() == ["a.py"]


def test_workspace_download_route_is_registered():
    """路由表应包含下载路径，且静态前端挂在最后（/api/* 优先匹配）。"""
    from app.main import create_app

    app = create_app()

    assert "/api/workspace/download" in app.openapi()["paths"]
    assert getattr(app.routes[-1], "path", None) == ""  # 静态前端挂载在最后