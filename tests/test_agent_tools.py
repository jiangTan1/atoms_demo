"""Agent 沙箱文件工具的单元测试。

直接注入构造的上下文调用工具函数，确认成功与失败路径返回的都是
可被模型理解的文本（失败不抛异常），见 specs/code-assistant-agent/spec.md
与 design.md 决策 6。沙箱根目录用 monkeypatch 指向临时目录。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent import tools
from app.services import workspace


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", root)
    return root


def make_context(session_id: str = "session-a"):
    """构造等价于 ToolContext 的假上下文：仅需 session.id。"""
    return SimpleNamespace(session=SimpleNamespace(id=session_id))


# --- write_file ---


def test_write_file_returns_path_and_size(sandbox):
    result = tools.write_file("src/main.py", "print(1)", make_context())

    assert result == "已写入 src/main.py（8 字节）。"
    assert workspace.read_file("session-a", "src/main.py") == "print(1)"


def test_write_file_reports_failure_as_text(sandbox):
    result = tools.write_file("/etc/passwd", "x", make_context())

    assert result.startswith("文件操作未生效：")
    assert "绝对路径" in result


# --- read_file ---


def test_read_file_returns_raw_content(sandbox):
    workspace.write_file("session-a", "readme.md", "# 标题")

    assert tools.read_file("readme.md", make_context()) == "# 标题"


def test_read_file_missing_returns_failure_text(sandbox):
    result = tools.read_file("ghost.py", make_context())

    assert result.startswith("文件操作未生效：")
    assert "不存在" in result


# --- list_files ---


def test_list_files_empty_sandbox_explains_no_files(sandbox):
    assert tools.list_files(make_context()) == workspace.EMPTY_WORKSPACE_TEXT


def test_list_files_includes_all_paths(sandbox):
    workspace.write_file("session-a", "a.py", "a")
    workspace.write_file("session-a", "src/b.py", "b")

    result = tools.list_files(make_context())

    assert "a.py" in result
    assert "src/b.py" in result


# --- delete_file ---


def test_delete_file_reports_success(sandbox):
    workspace.write_file("session-a", "tmp.py", "x")

    assert tools.delete_file("tmp.py", make_context()) == "已删除 tmp.py。"
    assert workspace.list_files("session-a") == []


def test_delete_file_missing_returns_failure_text(sandbox):
    result = tools.delete_file("ghost.py", make_context())

    assert result.startswith("文件操作未生效：")


# --- 装配 ---


def test_root_agent_only_exposes_sandbox_file_tools():
    """工具集恰为四个沙箱文件工具，不含执行命令或访问网络的工具。"""
    from app.agent.root_agent import root_agent

    resolved = asyncio.run(root_agent.canonical_tools())

    assert {tool.name for tool in resolved} == {
        "write_file",
        "read_file",
        "list_files",
        "delete_file",
    }