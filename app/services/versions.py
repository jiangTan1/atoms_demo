"""版本快照服务。

为每段会话保存沙箱内容的历史版本（`data/versions/<会话标识>/<版本标识>/`），
版本标识为单调递增的四位序号，每个版本目录是该会话沙箱内容的一次完整复制。

对应 specs/app-versions/spec.md，设计依据见 design.md 决策 4、5、8：

- 是否产生新版本由「本轮结束后沙箱指纹是否变化」判定，指纹经过文件清单与各文件内容哈希，
  未变化则不产生新版本；指纹状态随会话存于版本目录下的 `.state.json`，不写入 ADK 会话 state。
- 回滚先留存当前内容为一份新版本、再用目标版本整体重建沙箱，因此回滚可逆、历史不回退。
- 单会话版本数受 `VERSION_MAX_PER_SESSION` 限制，超出按最旧优先清理。
- 失败一律抛出 VersionError，消息为可直接展示给使用者的中文说明。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, Settings, get_settings
from app.services import workspace

# 版本快照根目录：与沙箱同层，data/ 已被 .gitignore 忽略
VERSIONS_ROOT = PROJECT_ROOT / "data" / "versions"

# 指纹索引文件：与数字版本目录并列，记录本会话上次快照时的指纹
STATE_FILE_NAME = ".state.json"

# 版本标识为四位十进制序号，上限 8 位以便按名字判定合法性
_MAX_VERSION_ID_LEN = 8


class VersionError(Exception):
    """版本操作被拒绝或失败。消息为可直接展示给使用者的中文说明。"""


def versions_dir(session_id: str) -> Path:
    """该会话的版本根目录（已解析真实路径，不保证已存在）。

    会话标识不可信任，与沙箱一样做越界校验。
    """
    root = VERSIONS_ROOT.resolve()
    base = (root / str(session_id)).resolve()
    if base != root and not base.is_relative_to(root):
        raise VersionError(f"会话标识 {session_id!r} 非法：不能指向版本根目录之外。")
    return base


def version_path(session_id: str, version_id: str) -> Path:
    """某个版本快照的目录；版本标识非法时拒绝。"""
    key = str(version_id).strip()
    if not (key.isdigit() and len(key) <= _MAX_VERSION_ID_LEN):
        raise VersionError(f"版本标识 {version_id!r} 非法，应为版本列表中的编号。")
    return versions_dir(session_id) / key


def _existing_ids(base: Path) -> list[int]:
    """版本目录下已存在的版本序号（升序）。"""
    if not base.is_dir():
        return []
    return sorted(
        int(child.name)
        for child in base.iterdir()
        if child.is_dir() and child.name.isdigit()
    )


def _next_version_id(base: Path) -> str:
    ids = _existing_ids(base)
    return f"{(ids[-1] + 1) if ids else 1:04d}"


def _record(base: Path, version_id: str) -> dict[str, Any]:
    return {
        "version_id": version_id,
        "created_at": float((base / version_id).stat().st_mtime),
    }


def _read_last_fingerprint(base: Path) -> str:
    state_path = base / STATE_FILE_NAME
    if not state_path.is_file():
        return ""
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = data.get("last_fingerprint") if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


def _write_last_fingerprint(base: Path, value: str) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / STATE_FILE_NAME).write_text(
        json.dumps({"last_fingerprint": value}, ensure_ascii=False), encoding="utf-8"
    )


def fingerprint(session_id: str) -> str:
    """会话沙箱内容的指纹：文件清单 + 各文件内容哈希的摘要。

    空沙箱也有确定的指纹（空摘要），因此「空 → 有内容」同样会被判定为变化。
    """
    base = workspace.workspace_dir(session_id)
    digest = hashlib.sha256()
    for relative in workspace.list_files(session_id):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        data = (base / relative).read_bytes()
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def list_versions(session_id: str) -> list[dict[str, Any]]:
    """该会话的全部版本，按时间倒序（版本序号降序）返回。"""
    base = versions_dir(session_id)
    records = [_record(base, f"{value:04d}") for value in _existing_ids(base)]
    records.sort(key=lambda record: record["version_id"], reverse=True)
    return records


def prune(session_id: str, settings: Settings | None = None) -> list[str]:
    """按上限清理最旧版本，返回被清理的版本标识列表。"""
    settings = settings or get_settings()
    base = versions_dir(session_id)
    ids = _existing_ids(base)
    removed: list[str] = []
    while len(ids) > settings.version_max_per_session:
        oldest = ids.pop(0)
        version_id = f"{oldest:04d}"
        shutil.rmtree(base / version_id, ignore_errors=True)
        removed.append(version_id)
    return removed


def snapshot_if_changed(
    session_id: str, settings: Settings | None = None
) -> dict[str, Any] | None:
    """沙箱指纹变化时创建新版本，返回该版本记录；无变化或沙箱为空时返回 None。

    这是「每轮自动快照」的落点：由对话流结束后驱动，以可观测的沙箱内容而非
    「本轮是否调用过写文件」判定，从而覆盖删除、覆盖为空等情形。
    """
    settings = settings or get_settings()
    if not workspace.list_files(session_id):
        return None

    base = versions_dir(session_id)
    current = fingerprint(session_id)
    if current == _read_last_fingerprint(base):
        return None

    version_id = _next_version_id(base)
    workspace.snapshot(session_id, base / version_id)
    _write_last_fingerprint(base, current)
    prune(session_id, settings)
    return _record(base, version_id)


def rollback(
    session_id: str, version_id: str, settings: Settings | None = None
) -> dict[str, Any]:
    """把沙箱恢复到指定版本；回滚前先留存当前内容为一份新版本，保证可逆。"""
    settings = settings or get_settings()
    base = versions_dir(session_id)
    target = version_path(session_id, version_id)
    if not target.is_dir():
        raise VersionError(f"版本 {version_id} 不存在，无法回滚。")

    # 先留存当前内容（沙箱为空时没有可留存的内容，不额外留档）
    preserved_id: str | None = None
    keep: Path | None = None
    if workspace.list_files(session_id):
        preserved_id = _next_version_id(base)
        keep = base / preserved_id

    workspace.restore(session_id, target, keep)
    _write_last_fingerprint(base, fingerprint(session_id))
    prune(session_id, settings)
    return {"version_id": version_id, "preserved_version_id": preserved_id}