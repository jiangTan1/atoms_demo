"""账号与登录态服务。

在独立的 `data/users.db` 中保存账号（用户名、密码哈希、角色、来源、创建时间）
与登录态令牌，对外提供格式校验、注册、凭据校验、改密、管理员用户管理，
以及令牌的签发、校验与吊销。

对应 specs/user-accounts/spec.md 与 specs/access-control/spec.md，
设计依据见本变更 design.md 决策 1、2、5、6、7：

- 账号与登录态独立成库，与 ADK 持有的 `data/sessions.db` 解耦，`SESSION_BACKEND=memory`
  时账号依然持久化。
- 密码只存 `pbkdf2_sha256$<迭代数>$<盐>$<哈希>`，校验用 `hmac.compare_digest()`。
- 「普通用户 99 上限」的口径是 `role='user' AND source='self'` 的行数，
  内置管理员（`system`，首个管理员）与管理员新增的账号（`admin`）不占名额。
- 失败一律抛出 AccountError 子类，消息为可直接展示给使用者的中文说明。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from app.config import (
    MAX_CREDENTIAL_LEN,
    MIN_CREDENTIAL_LEN,
    PROJECT_ROOT,
    ConfigError,
)

# 账号库与会话库同层，data/ 已被 .gitignore 忽略
USERS_DB_PATH = PROJECT_ROOT / "data" / "users.db"

ROLE_ADMIN = "admin"
ROLE_USER = "user"

# 账号来源：系统内置 / 自助注册 / 管理员新增
SOURCE_SYSTEM = "system"
SOURCE_SELF = "self"
SOURCE_ADMIN = "admin"

# 自助注册的普通用户上限
MAX_SELF_REGISTERED_USERS = 99

# 登录态有效期：1 天
TOKEN_TTL_SECONDS = 86400

_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ITERATIONS = 260000
_SALT_BYTES = 16

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    source        TEXT NOT NULL,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS login_tokens (
    token      TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_tokens_username ON login_tokens (username);
"""


class AccountError(Exception):
    """账号操作被拒绝。消息为可直接展示给使用者的中文说明。"""


class AccountPermissionError(AccountError):
    """操作者不具备执行该操作的权限。"""


class AccountNotFoundError(AccountError):
    """目标账号不存在。"""


@dataclass(frozen=True)
class Account:
    """一个账号（不含密码哈希）。"""

    username: str
    role: str
    source: str
    created_at: float

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


# --- 密码哈希 ---


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    """生成 `pbkdf2_sha256$<迭代数>$<盐>$<哈希>` 形式的存储串。"""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _HASH_ITERATIONS
    )
    return f"{_HASH_ALGORITHM}${_HASH_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """按存储串中的算法参数重算哈希并做定时安全比较。"""
    try:
        algorithm, iterations, salt_b64, digest_b64 = str(stored).split("$")
        if algorithm != _HASH_ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        rounds = int(iterations)
    except (ValueError, TypeError, binascii.Error):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(candidate, expected)


# --- 格式约束 ---


def _check_length(field: str, value: str) -> str:
    stripped = (value or "").strip()
    if not MIN_CREDENTIAL_LEN <= len(stripped) <= MAX_CREDENTIAL_LEN:
        raise AccountError(
            f"{field}长度需为 {MIN_CREDENTIAL_LEN} 到 {MAX_CREDENTIAL_LEN} 个字符，"
            f"当前为 {len(stripped)} 个字符。"
        )
    return stripped


def validate_username(username: str) -> str:
    return _check_length("用户名", username)


def validate_password(password: str) -> str:
    return _check_length("密码", password)


class AccountService:
    """账号库的全部读写入口。db_path 可注入，便于测试指向临时目录。"""

    def __init__(self, db_path: Path | str = USERS_DB_PATH) -> None:
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

    # --- 初始数据 ---

    def ensure_admin(self, username: str | None, password: str | None) -> bool:
        """账号库为空时用给定凭据创建首个管理员；库非空则不做任何写入。

        凭据来自配置项 `ADMIN_USERNAME` / `ADMIN_PASSWORD`：首次启动（账号库为空）
        必须提供，缺失或非法时抛出 ConfigError 并点名配置项，使启动直接失败。
        库非空后这两项可以留空，已创建的管理员不会被覆盖、重置或重建。
        """
        with self._transaction() as conn:
            total = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            if total:
                return False
            if not username:
                raise ConfigError(
                    "ADMIN_USERNAME",
                    "缺失：账号库为空，需要用它指定首个管理员的用户名（写入 .env）",
                )
            if not password:
                raise ConfigError(
                    "ADMIN_PASSWORD",
                    "缺失：账号库为空，需要用它指定首个管理员的密码（写入 .env）",
                )
            try:
                username = validate_username(username)
            except AccountError as exc:
                raise ConfigError("ADMIN_USERNAME", str(exc)) from exc
            try:
                password = validate_password(password)
            except AccountError as exc:
                raise ConfigError("ADMIN_PASSWORD", str(exc)) from exc
            conn.execute(
                "INSERT INTO accounts (username, password_hash, role, source, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    username,
                    hash_password(password),
                    ROLE_ADMIN,
                    SOURCE_SYSTEM,
                    time.time(),
                ),
            )
            return True

    # --- 读取 ---

    def get_account(self, username: str) -> Account | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, role, source, created_at FROM accounts WHERE username = ?",
                (username,),
            ).fetchone()
        return _to_account(row)

    def count_self_registered(self) -> int:
        """自助注册的普通用户数，用于判定 99 上限。"""
        with self._connection() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM accounts WHERE role = ? AND source = ?",
                    (ROLE_USER, SOURCE_SELF),
                ).fetchone()[0]
            )

    # --- 注册与凭据 ---

    def register(self, username: str, password: str) -> Account:
        """自助注册：一律普通用户，且受 99 上限约束。"""
        username = validate_username(username)
        password = validate_password(password)
        created_at = time.time()
        with self._transaction() as conn:
            if _username_taken(conn, username):
                raise AccountError(f"用户名 {username} 已被使用，请换一个。")
            count = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE role = ? AND source = ?",
                (ROLE_USER, SOURCE_SELF),
            ).fetchone()[0]
            if count >= MAX_SELF_REGISTERED_USERS:
                raise AccountError(
                    f"普通用户已达注册上限（最多 {MAX_SELF_REGISTERED_USERS} 个），"
                    "无法再注册新账号。"
                )
            conn.execute(
                "INSERT INTO accounts (username, password_hash, role, source, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (username, hash_password(password), ROLE_USER, SOURCE_SELF, created_at),
            )
        return Account(
            username=username, role=ROLE_USER, source=SOURCE_SELF, created_at=created_at
        )

    def verify_credentials(self, username: str, password: str) -> Account | None:
        """校验用户名与密码。

        用户名不存在与密码错误一律返回 None：调用方给出的提示必须一致，
        且两种情况都做一次哈希计算，避免响应时间透露用户名是否存在。
        """
        candidate = (username or "").strip()
        secret = (password or "").strip()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, role, source, created_at, password_hash"
                " FROM accounts WHERE username = ?",
                (candidate,),
            ).fetchone()
        if row is None:
            hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), b"", _HASH_ITERATIONS)
            return None
        if not verify_password(secret, row["password_hash"]):
            return None
        return _to_account(row)

    def change_password(self, username: str, old_password: str, new_password: str) -> None:
        """修改自己的密码：必须提供正确的原密码。"""
        new_password = validate_password(new_password)
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT password_hash FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            if row is None or not verify_password(
                (old_password or "").strip(), row["password_hash"]
            ):
                raise AccountError("原密码不正确，密码未修改。")
            conn.execute(
                "UPDATE accounts SET password_hash = ? WHERE username = ?",
                (hash_password(new_password), username),
            )

    # --- 管理员用户管理 ---

    def create_user(self, actor: Account, username: str, password: str) -> Account:
        """管理员新增用户：来源记为 admin，不占自助注册名额。"""
        _require_admin(actor)
        username = validate_username(username)
        password = validate_password(password)
        created_at = time.time()
        with self._transaction() as conn:
            if _username_taken(conn, username):
                raise AccountError(f"用户名 {username} 已被使用，请换一个。")
            conn.execute(
                "INSERT INTO accounts (username, password_hash, role, source, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (username, hash_password(password), ROLE_USER, SOURCE_ADMIN, created_at),
            )
        return Account(
            username=username, role=ROLE_USER, source=SOURCE_ADMIN, created_at=created_at
        )

    def reset_password(self, actor: Account, username: str, new_password: str) -> None:
        """管理员重置任意用户的密码，无需原密码；重置后该用户全部登录态失效。"""
        _require_admin(actor)
        new_password = validate_password(new_password)
        with self._transaction() as conn:
            if not _username_taken(conn, username):
                raise AccountNotFoundError(f"用户 {username} 不存在。")
            conn.execute(
                "UPDATE accounts SET password_hash = ? WHERE username = ?",
                (hash_password(new_password), username),
            )
            conn.execute("DELETE FROM login_tokens WHERE username = ?", (username,))

    def delete_user(self, actor: Account, username: str) -> None:
        """管理员删除用户；内置管理员（source='system'）不可删除，避免把自己锁在门外。"""
        _require_admin(actor)
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT source FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            if row is None:
                raise AccountNotFoundError(f"用户 {username} 不存在。")
            if row["source"] == SOURCE_SYSTEM:
                raise AccountError("默认管理员账号不能被删除。")
            conn.execute("DELETE FROM accounts WHERE username = ?", (username,))
            conn.execute("DELETE FROM login_tokens WHERE username = ?", (username,))

    # --- 登录态令牌 ---

    def issue_token(self, username: str) -> str:
        """签发登录态令牌，有效期 1 天；签发前清理该用户的过期记录。"""
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._transaction() as conn:
            conn.execute(
                "DELETE FROM login_tokens WHERE username = ? AND expires_at <= ?",
                (username, now),
            )
            conn.execute(
                "INSERT INTO login_tokens (token, username, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (token, username, now, now + TOKEN_TTL_SECONDS),
            )
        return token

    def verify_token(self, token: str) -> Account | None:
        """校验令牌；过期、不存在或账号已删除一律视为未登录。"""
        raw = (token or "").strip()
        if not raw:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT a.username, a.role, a.source, a.created_at, t.expires_at"
                " FROM login_tokens AS t JOIN accounts AS a ON a.username = t.username"
                " WHERE t.token = ?",
                (raw,),
            ).fetchone()
        if row is None or float(row["expires_at"]) <= time.time():
            return None
        return _to_account(row)

    def revoke_token(self, token: str) -> None:
        """退出登录：删除当前令牌。"""
        with self._transaction() as conn:
            conn.execute(
                "DELETE FROM login_tokens WHERE token = ?", ((token or "").strip(),)
            )

    def revoke_other_tokens(self, username: str, keep_token: str) -> None:
        """改密后使该用户的其他登录态失效，保留发起改密的那个令牌。"""
        with self._transaction() as conn:
            conn.execute(
                "DELETE FROM login_tokens WHERE username = ? AND token != ?",
                (username, (keep_token or "").strip()),
            )


def _require_admin(actor: Account | None) -> None:
    if actor is None or actor.role != ROLE_ADMIN:
        raise AccountPermissionError("该操作仅管理员可用。")


def _username_taken(conn: sqlite3.Connection, username: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM accounts WHERE username = ?", (username,)).fetchone()
        is not None
    )


def _to_account(row: sqlite3.Row | None) -> Account | None:
    if row is None:
        return None
    return Account(
        username=row["username"],
        role=row["role"],
        source=row["source"],
        created_at=float(row["created_at"]),
    )