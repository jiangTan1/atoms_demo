"""分享服务的单元测试。

覆盖建表幂等、创建后可解析到对应版本快照、撤销后不可用、随机 token 不可解析，
以及创建者归属与「版本必须已存在」的约束（见 specs/app-sharing/spec.md）。

沙箱与版本根目录指向临时目录，分享库也落在临时目录，避免污染项目 data/。
"""

from __future__ import annotations

import pytest

from app.config import load_settings
from app.services import shares, versions, workspace
from app.services.shares import ShareError, ShareService

BASE_ENV = {
    "LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "LLM_MODEL": "glm-4.5-flash",
    "LLM_API_KEY": "sk-test-1234567890",
    "SESSION_BACKEND": "memory",
}

ALICE = "user:alice"
BOB = "user:bob"


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(versions, "VERSIONS_ROOT", tmp_path / "versions")
    return tmp_path


@pytest.fixture
def service(tmp_path):
    return ShareService(tmp_path / "shares.db")


def make_version(session_id: str = "s1", content: str = "<h1>A</h1>") -> str:
    """写一个入口文件并生成版本 0001，返回版本标识。"""
    workspace.write_file(session_id, "index.html", content)
    record = versions.snapshot_if_changed(session_id, load_settings(BASE_ENV))
    assert record is not None
    return record["version_id"]


# --- 建表与 token ---


def test_schema_creation_is_idempotent(service, tmp_path):
    again = ShareService(tmp_path / "shares.db")

    assert again.list_for(ALICE, "s1") == []


def test_tokens_are_long_and_distinct(service, roots):
    version_id = make_version()

    first = service.create("s1", version_id, ALICE)["token"]
    second = service.create("s1", version_id, ALICE)["token"]

    assert first != second
    assert len(first) >= 32


def test_share_url_points_at_the_public_read_only_route(service, roots):
    version_id = make_version()

    token = service.create("s1", version_id, ALICE)["token"]

    assert shares.share_url(token) == f"/share/{token}/"


# --- 创建与解析 ---


def test_created_share_resolves_to_the_version_snapshot(service, roots):
    version_id = make_version()

    token = service.create("s1", version_id, ALICE)["token"]
    record = service.resolve(token)

    assert record is not None
    assert record["session_id"] == "s1"
    assert record["version_id"] == version_id
    assert record["created_by"] == ALICE
    snapshot = shares.snapshot_dir(record["session_id"], record["version_id"])
    assert (snapshot / "index.html").read_text(encoding="utf-8") == "<h1>A</h1>"


def test_share_content_is_pinned_to_the_selected_version(service, roots):
    """分享后继续改动沙箱，已生成的分享仍指向生成时所选的版本。"""
    version_id = make_version()
    token = service.create("s1", version_id, ALICE)["token"]

    workspace.write_file("s1", "index.html", "<h1>B</h1>")

    record = service.resolve(token)
    snapshot = shares.snapshot_dir(record["session_id"], record["version_id"])
    assert (snapshot / "index.html").read_text(encoding="utf-8") == "<h1>A</h1>"


def test_random_token_does_not_resolve(service, roots):
    make_version()

    assert service.resolve("not-a-real-token") is None
    assert service.resolve("") is None


def test_creating_a_share_for_a_missing_version_is_rejected(service, roots):
    make_version()

    with pytest.raises(ShareError) as excinfo:
        service.create("s1", "0009", ALICE)

    assert "0009" in str(excinfo.value)
    assert service.list_for(ALICE, "s1") == []


def test_creating_a_share_with_an_invalid_version_id_is_rejected(service, roots):
    with pytest.raises(ShareError):
        service.create("s1", "../../etc", ALICE)


# --- 列出与撤销 ---


def test_list_returns_only_own_shares_of_the_session(service, roots):
    version_id = make_version("s1")
    other_version = make_version("s2")
    service.create("s1", version_id, ALICE)
    service.create("s1", version_id, BOB)
    service.create("s2", other_version, ALICE)

    own = service.list_for(ALICE, "s1")

    assert len(own) == 1
    assert own[0]["created_by"] == ALICE
    assert own[0]["session_id"] == "s1"


def test_list_is_newest_first(service, roots):
    version_id = make_version()
    first = service.create("s1", version_id, ALICE)["token"]
    second = service.create("s1", version_id, ALICE)["token"]

    tokens = [record["token"] for record in service.list_for(ALICE, "s1")]

    assert tokens == [second, first]


def test_revoke_makes_the_link_unusable(service, roots):
    version_id = make_version()
    token = service.create("s1", version_id, ALICE)["token"]

    service.revoke(token, ALICE)

    assert service.resolve(token) is None
    assert service.list_for(ALICE, "s1") == []


def test_revoke_only_works_for_the_creator(service, roots):
    version_id = make_version()
    token = service.create("s1", version_id, ALICE)["token"]

    with pytest.raises(ShareError):
        service.revoke(token, BOB)

    assert service.resolve(token) is not None


def test_revoke_unknown_token_is_rejected(service, roots):
    with pytest.raises(ShareError) as excinfo:
        service.revoke("not-a-real-token", ALICE)

    assert "不存在" in str(excinfo.value)