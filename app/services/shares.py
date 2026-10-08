"""应用分享服务。

在独立的 `data/shares.db` 中保存分享记录（`token`、会话标识、版本标识、创建者、创建时间），
对外提供创建、按会话与创建者列出、撤销，以及按 token 解析出「被分享的版本快照目录」。

对应 specs/app-sharing/spec.md，设计依据见 design.md 决策 6、10：

- 分享独立成库，与账号库（`users.db`）和 ADK 持有的会话库（`sessions.db`）解耦，
  不会随 `SESSION_BACKEND` 变化。
- 分享指向**版本快照**而不是当前沙箱，因此链接内容稳定，不随后续对话漂移；
  分享预览也就不需要读会话，只读快照目录即可。
- token 用 `secrets.token_urlsafe(32)` 生成，足够随机、不可枚举。
- 失败一律抛出 ShareError，消息为可直接展示给使用者的中文说明。
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.config import PROJECT_ROOT
from app.services import versions

# 分享库位置：与账号库、沙箱同层，data/ 已被 .gitignore 忽略
SHARES_DB_PATH = PROJECT_ROOT / "data" / "shares.db"

# token 的随机字节数，对应链接中不可枚举的标识
TOKEN_BYTES = 32

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS shares (
    token      TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shares_owner ON shares (created_by, session_id);
"""


class ShareError(Exception):
    """分享操作被拒绝或失败。消息为可直接展示给使用者的中文说明。"""


def _to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "token": row["token"],
        "session_id": row["session_id"],
        "version_id": row["version_id"],
        "created_by": row["created_by"],
        "created_at": float(row["created_at"]),
    }


def share_url(token: str) -> str:
    """分享链接的相对地址；前端据此拼出可复制的完整链接。"""
    return f"/share/{token}/"


def snapshot_dir(session_id: str, version_id: str) -> Path:
    """被分享版本对应的快照目录；版本标识非法时按分享不可用处理。"""
    try:
        return versions.version_path(session_id, version_id)
    except versions.VersionError as exc:
        raise ShareError(str(exc)) from exc


class ShareService:
    """分享库的全部读写入口。db_path 可注入，便于测试指向临时目录。"""

    def __init__(self, db_path: Path | str = SHARES_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # --- 连接与事务 ---

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """写事务：先 BEGIN IMMEDIATE 占写锁，再执行，异常时回滚。"""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(_SCHEMA_SQL)

    # --- 写入 ---

    def create(self, session_id: str, version_id: str, owner: str) -> dict[str, Any]:
        """为某个版本生成分享链接。

        版本必须已存在（分享指向的是快照，快照不在就无从分享）；owner 为创建者标识
        （`user:<登录用户名>`），只有创建者本人能列出与撤销该分享。
        """
        target = snapshot_dir(session_id, version_id)
        if not target.is_dir():
            raise ShareError(f"版本 {version_id} 不存在，无法生成分享链接。")

        token = secrets.token_urlsafe(TOKEN_BYTES)
        created_at = time.time()
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO shares (token, session_id, version_id, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (token, session_id, version_id, owner, created_at),
            )
        return {
            "token": token,
            "session_id": session_id,
            "version_id": version_id,
            "created_by": owner,
            "created_at": created_at,
        }

    def revoke(self, token: str, owner: str) -> str:
        """撤销自己创建的分享；不存在或不属于自己的一律按不存在处理。"""
        key = (token or "").strip()
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT created_by FROM shares WHERE token = ?", (key,)
            ).fetchone()
            if row is None or row["created_by"] != owner:
                raise ShareError("该分享不存在或已被撤销。")
            conn.execute("DELETE FROM shares WHERE token = ?", (key,))
        return key

    # --- 读取 ---

    def list_for(self, owner: str, session_id: str) -> list[dict[str, Any]]:
        """某个会话下由该使用者创建的分享，按创建时间倒序。"""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT token, session_id, version_id, created_by, created_at FROM shares"
                " WHERE created_by = ? AND session_id = ? ORDER BY created_at DESC, token",
                (owner, session_id),
            ).fetchall()
        return [_to_record(row) for row in rows]

    def resolve(self, token: str) -> dict[str, Any] | None:
        """按 token 解析分享记录；不存在或已撤销时返回 None（分享预览用，免登录）。"""
        key = (token or "").strip()
        if not key:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT token, session_id, version_id, created_by, created_at FROM shares"
                " WHERE token = ?",
                (key,),
            ).fetchone()
        return _to_record(row) if row is not None else None