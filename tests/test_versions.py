"""版本快照服务的单元测试。

覆盖指纹比对、按需创建快照、按时间倒序列出、回滚可逆与按上限清理
（见 specs/app-versions/spec.md）。

沙箱与版本根目录都用 monkeypatch 指向临时目录，避免污染项目 data/。
"""

from __future__ import annotations

import pytest

from app.config import Settings, load_settings
from app.services import versions, workspace

BASE_ENV = {
    "LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "LLM_MODEL": "glm-4.5-flash",
    "LLM_API_KEY": "sk-test-1234567890",
    "SESSION_BACKEND": "memory",
}


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """把沙箱与版本根目录都指向临时目录，返回该临时根目录。"""
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(versions, "VERSIONS_ROOT", tmp_path / "versions")
    return tmp_path


def make_settings(**overrides) -> Settings:
    env = {**BASE_ENV, **{key: str(value) for key, value in overrides.items()}}
    return load_settings(env)


def version_ids(session_id: str) -> list[str]:
    """已存在的版本标识（升序），用于直观看清清理结果。"""
    base = versions.versions_dir(session_id)
    if not base.is_dir():
        return []
    return sorted(child.name for child in base.iterdir() if child.is_dir())


# --- 指纹与快照创建 ---


def test_empty_sandbox_produces_no_version(roots):
    assert versions.snapshot_if_changed("s1", make_settings()) is None
    assert versions.list_versions("s1") == []


def test_first_snapshot_records_the_current_content(roots):
    workspace.write_file("s1", "index.html", "<h1>A</h1>")

    record = versions.snapshot_if_changed("s1", make_settings())

    assert record is not None
    assert record["version_id"] == "0001"
    snapshot = versions.version_path("s1", "0001") / "index.html"
    assert snapshot.read_text(encoding="utf-8") == "<h1>A</h1>"


def test_unchanged_sandbox_produces_no_new_version(roots):
    workspace.write_file("s1", "index.html", "<h1>A</h1>")
    versions.snapshot_if_changed("s1", make_settings())

    assert versions.snapshot_if_changed("s1", make_settings()) is None
    assert version_ids("s1") == ["0001"]


def test_changed_sandbox_produces_a_new_version(roots):
    workspace.write_file("s1", "index.html", "<h1>A</h1>")
    versions.snapshot_if_changed("s1", make_settings())
    workspace.write_file("s1", "index.html", "<h1>B</h1>")

    record = versions.snapshot_if_changed("s1", make_settings())

    assert record is not None
    assert record["version_id"] == "0002"
    assert version_ids("s1") == ["0001", "0002"]


def test_deleting_a_file_also_counts_as_a_change(roots):
    workspace.write_file("s1", "index.html", "<h1>A</h1>")
    workspace.write_file("s1", "old.css", "body{}")
    versions.snapshot_if_changed("s1", make_settings())
    workspace.delete_file("s1", "old.css")

    record = versions.snapshot_if_changed("s1", make_settings())

    assert record is not None
    assert record["version_id"] == "0002"


def test_snapshot_does_not_follow_later_edits(roots):
    workspace.write_file("s1", "index.html", "<h1>A</h1>")
    versions.snapshot_if_changed("s1", make_settings())

    workspace.write_file("s1", "index.html", "<h1>B</h1>")

    snapshot = versions.version_path("s1", "0001") / "index.html"
    assert snapshot.read_text(encoding="utf-8") == "<h1>A</h1>"


def test_versions_are_listed_newest_first(roots):
    for content in ("A", "B", "C"):
        workspace.write_file("s1", "index.html", content)
        versions.snapshot_if_changed("s1", make_settings())

    listed = [record["version_id"] for record in versions.list_versions("s1")]

    assert listed == ["0003", "0002", "0001"]


def test_versions_are_isolated_between_sessions(roots):
    workspace.write_file("s1", "index.html", "A")
    versions.snapshot_if_changed("s1", make_settings())
    workspace.write_file("s2", "index.html", "B")
    versions.snapshot_if_changed("s2", make_settings())

    workspace.write_file("s2", "index.html", "C")
    versions.snapshot_if_changed("s2", make_settings())

    assert version_ids("s1") == ["0001"]
    assert version_ids("s2") == ["0001", "0002"]
    assert (
        versions.version_path("s1", "0001") / "index.html"
    ).read_text(encoding="utf-8") == "A"


# --- 回滚 ---


def test_rollback_restores_the_target_content(roots):
    workspace.write_file("s1", "index.html", "A")
    versions.snapshot_if_changed("s1", make_settings())
    workspace.write_file("s1", "index.html", "B")
    versions.snapshot_if_changed("s1", make_settings())

    versions.rollback("s1", "0001", make_settings())

    assert workspace.read_file("s1", "index.html") == "A"


def test_rollback_preserves_the_content_it_replaced(roots):
    workspace.write_file("s1", "index.html", "A")
    versions.snapshot_if_changed("s1", make_settings())
    workspace.write_file("s1", "index.html", "B")
    versions.snapshot_if_changed("s1", make_settings())

    result = versions.rollback("s1", "0001", make_settings())

    preserved = result["preserved_version_id"]
    assert preserved == "0003"
    assert (
        versions.version_path("s1", preserved) / "index.html"
    ).read_text(encoding="utf-8") == "B"


def test_rollback_is_reversible(roots):
    workspace.write_file("s1", "index.html", "A")
    versions.snapshot_if_changed("s1", make_settings())
    workspace.write_file("s1", "index.html", "B")
    versions.snapshot_if_changed("s1", make_settings())

    preserved = versions.rollback("s1", "0001", make_settings())["preserved_version_id"]
    versions.rollback("s1", preserved, make_settings())

    assert workspace.read_file("s1", "index.html") == "B"


def test_rollback_keeps_the_history_intact(roots):
    workspace.write_file("s1", "index.html", "A")
    versions.snapshot_if_changed("s1", make_settings())
    workspace.write_file("s1", "index.html", "B")
    versions.snapshot_if_changed("s1", make_settings())

    versions.rollback("s1", "0001", make_settings())

    # 回滚不减少版本条目：被跨过的 0002 与回滚前的 0003 都还在
    assert version_ids("s1") == ["0001", "0002", "0003"]


def test_rollback_unknown_version_is_rejected(roots):
    workspace.write_file("s1", "index.html", "A")
    versions.snapshot_if_changed("s1", make_settings())

    with pytest.raises(versions.VersionError) as excinfo:
        versions.rollback("s1", "0009", make_settings())

    assert "0009" in str(excinfo.value)
    assert workspace.read_file("s1", "index.html") == "A"


def test_rollback_rejects_a_non_numeric_version_id(roots):
    with pytest.raises(versions.VersionError):
        versions.rollback("s1", "../../etc", make_settings())


def test_rollback_into_an_empty_sandbox_keeps_nothing_extra(roots):
    """沙箱为空时回滚没有可留存的内容，不额外产生「回滚前」版本。"""
    workspace.write_file("s1", "index.html", "A")
    versions.snapshot_if_changed("s1", make_settings())
    workspace.delete_file("s1", "index.html")

    result = versions.rollback("s1", "0001", make_settings())

    assert result["preserved_version_id"] is None
    assert version_ids("s1") == ["0001"]
    assert workspace.read_file("s1", "index.html") == "A"


# --- 按上限清理 ---


def test_prune_keeps_only_the_newest_versions(roots):
    settings = make_settings(VERSION_MAX_PER_SESSION=2)

    for content in ("A", "B", "C"):
        workspace.write_file("s1", "index.html", content)
        versions.snapshot_if_changed("s1", settings)

    assert version_ids("s1") == ["0002", "0003"]


def test_prune_never_removes_more_than_the_limit(roots):
    settings = make_settings(VERSION_MAX_PER_SESSION=1)

    for content in ("A", "B"):
        workspace.write_file("s1", "index.html", content)
        versions.snapshot_if_changed("s1", settings)

    assert version_ids("s1") == ["0002"]


def test_prune_tolerates_a_zero_sized_history(roots):
    assert versions.prune("s1", make_settings()) == []