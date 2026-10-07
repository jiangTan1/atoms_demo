"""账号服务单元测试。

覆盖账号表与登录态表的建表幂等、密码哈希与校验、默认管理员初始化、
格式约束、自助注册与 99 上限、凭据校验、改密、管理员用户管理与登录态令牌
（见 openspec/changes/add-user-authentication/tasks.md 的第 1、2 组任务）。
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from app.services import accounts
from app.services.accounts import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    MAX_SELF_REGISTERED_USERS,
    ROLE_ADMIN,
    ROLE_USER,
    SOURCE_ADMIN,
    SOURCE_SELF,
    SOURCE_SYSTEM,
    AccountError,
    AccountNotFoundError,
    AccountPermissionError,
    AccountService,
    hash_password,
    verify_password,
)


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    """把 PBKDF2 迭代数调低：99 个账号的用例否则会因哈希而耗时过长。"""
    monkeypatch.setattr(accounts, "_HASH_ITERATIONS", 1000)


@pytest.fixture
def service(tmp_path):
    return AccountService(tmp_path / "users.db")


@pytest.fixture
def admin(service):
    service.ensure_default_admin()
    return service.get_account(DEFAULT_ADMIN_USERNAME)


def read_hash(db_path, username):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT password_hash FROM accounts WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def add_self_registered(service, username, password="pass-123"):
    """直接落库，用于快速把自助注册数推到边界。"""
    with service._transaction() as conn:
        conn.execute(
            "INSERT INTO accounts (username, password_hash, role, source, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (username, hash_password(password), ROLE_USER, SOURCE_SELF, 0),
        )


# --- 1.2 建表幂等 ---


def test_schema_creation_is_idempotent(tmp_path):
    db_path = tmp_path / "users.db"
    first = AccountService(db_path)
    first.ensure_default_admin()

    second = AccountService(db_path)  # 重复初始化不报错
    second.ensure_default_admin()

    assert second.get_account(DEFAULT_ADMIN_USERNAME) is not None
    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    finally:
        conn.close()
    assert total == 1


def test_tables_and_columns_are_created(service):
    conn = sqlite3.connect(service.db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        account_columns = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
        token_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(login_tokens)")
        }
    finally:
        conn.close()

    assert {"accounts", "login_tokens"} <= tables
    assert account_columns == {"username", "password_hash", "role", "source", "created_at"}
    assert token_columns == {"token", "username", "created_at", "expires_at"}


def test_existing_rows_survive_reinitialization(tmp_path):
    db_path = tmp_path / "users.db"
    service = AccountService(db_path)
    service.ensure_default_admin()

    AccountService(db_path)  # 再次打开同一库

    assert service.get_account(DEFAULT_ADMIN_USERNAME).role == ROLE_ADMIN


# --- 1.3 密码哈希与校验 ---


def test_same_password_hashes_differently_but_both_verify():
    first = hash_password("secret-1")
    second = hash_password("secret-1")

    assert first != second  # 每次都用新盐
    assert verify_password("secret-1", first)
    assert verify_password("secret-1", second)


def test_wrong_password_fails_verification():
    stored = hash_password("secret-1")

    assert verify_password("secret-2", stored) is False


def test_stored_hash_does_not_contain_plaintext():
    stored = hash_password("plaintext-password")

    assert "plaintext-password" not in stored
    assert stored.startswith("pbkdf2_sha256$")


def test_malformed_stored_hash_is_rejected():
    assert verify_password("whatever", "not-a-valid-hash") is False


# --- 1.4 默认管理员初始化 ---


def test_default_admin_is_created_on_empty_store(service):
    created = service.ensure_default_admin()

    account = service.get_account(DEFAULT_ADMIN_USERNAME)
    assert created is True
    assert account is not None
    assert account.role == ROLE_ADMIN
    assert account.source == SOURCE_SYSTEM
    assert verify_password(DEFAULT_ADMIN_PASSWORD, read_hash(service.db_path, "root"))


def test_existing_accounts_are_not_overwritten(tmp_path):
    db_path = tmp_path / "users.db"
    service = AccountService(db_path)
    service.ensure_default_admin()

    # 模拟使用者已改过 root 密码
    changed = hash_password("changed-password")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE accounts SET password_hash = ? WHERE username = ?",
            (changed, DEFAULT_ADMIN_USERNAME),
        )
        conn.commit()
    finally:
        conn.close()

    created = service.ensure_default_admin()

    assert created is False
    current = read_hash(db_path, DEFAULT_ADMIN_USERNAME)
    assert verify_password("changed-password", current)
    assert not verify_password(DEFAULT_ADMIN_PASSWORD, current)


def test_non_default_admin_account_blocks_initialization(tmp_path):
    db_path = tmp_path / "users.db"
    service = AccountService(db_path)
    with service._transaction() as conn:
        conn.execute(
            "INSERT INTO accounts (username, password_hash, role, source, created_at)"
            " VALUES (?, ?, ?, ?, 0)",
            ("alice", hash_password("alice-1"), ROLE_USER, SOURCE_SELF),
        )

    created = service.ensure_default_admin()

    assert created is False
    assert service.get_account(DEFAULT_ADMIN_USERNAME) is None


# --- 2.1 格式约束 ---


@pytest.mark.parametrize("username", ["ab", "a" * 21])
def test_username_length_out_of_range_is_rejected(service, username):
    with pytest.raises(AccountError) as excinfo:
        service.register(username, "pass-123")

    assert "用户名" in str(excinfo.value)
    assert "3" in str(excinfo.value) and "20" in str(excinfo.value)


@pytest.mark.parametrize("password", ["ab", "p" * 21])
def test_password_length_out_of_range_is_rejected(service, password):
    with pytest.raises(AccountError) as excinfo:
        service.register("alice", password)

    assert "密码" in str(excinfo.value)
    assert "3" in str(excinfo.value) and "20" in str(excinfo.value)


def test_legal_lengths_are_accepted(service):
    short_ok = service.register("abc", "xyz")
    long_ok = service.register("u" * 20, "p" * 20)

    assert short_ok.role == ROLE_USER
    assert long_ok.username == "u" * 20


def test_surrounding_whitespace_is_ignored_when_measuring(service):
    account = service.register("  alice  ", "  pass-123  ")

    assert account.username == "alice"
    assert service.verify_credentials("alice", "pass-123") is not None


# --- 2.2 自助注册与 99 上限 ---


def test_register_creates_an_ordinary_user(service):
    account = service.register("alice", "pass-123")

    assert account.role == ROLE_USER
    assert account.source == SOURCE_SELF
    assert service.verify_credentials("alice", "pass-123").role == ROLE_USER


def test_duplicate_username_is_rejected(service):
    service.register("alice", "pass-123")

    with pytest.raises(AccountError) as excinfo:
        service.register("alice", "other-123")

    assert "已被使用" in str(excinfo.value)
    assert service.verify_credentials("alice", "pass-123") is not None


def test_ninety_ninth_user_is_accepted_and_hundredth_is_rejected(service):
    for index in range(MAX_SELF_REGISTERED_USERS - 1):
        add_self_registered(service, f"user{index:03d}")

    service.register("last-one", "pass-123")  # 第 99 个

    assert service.count_self_registered() == MAX_SELF_REGISTERED_USERS
    with pytest.raises(AccountError) as excinfo:
        service.register("one-too-many", "pass-123")
    assert "上限" in str(excinfo.value)


def test_default_admin_does_not_consume_the_registration_quota(admin, service):
    assert admin.role == ROLE_ADMIN

    for index in range(MAX_SELF_REGISTERED_USERS):
        service.register(f"user{index:03d}", "pass-123")

    assert service.count_self_registered() == MAX_SELF_REGISTERED_USERS
    with pytest.raises(AccountError):
        service.register("one-too-many", "pass-123")


# --- 2.3 凭据校验 ---


def test_unknown_user_and_wrong_password_are_indistinguishable(service):
    service.register("alice", "pass-123")

    unknown = service.verify_credentials("nobody", "pass-123")
    wrong = service.verify_credentials("alice", "wrong-123")

    assert unknown is None
    assert wrong is None


def test_correct_credentials_are_accepted(service):
    service.register("alice", "pass-123")

    account = service.verify_credentials("alice", "pass-123")

    assert account is not None
    assert account.username == "alice"


# --- 2.4 修改自己的密码 ---


def test_change_password_with_correct_old_password(service):
    service.register("alice", "pass-123")

    service.change_password("alice", "pass-123", "new-pass-1")

    assert service.verify_credentials("alice", "new-pass-1") is not None
    assert service.verify_credentials("alice", "pass-123") is None


def test_change_password_with_wrong_old_password_keeps_the_old_one(service):
    service.register("alice", "pass-123")

    with pytest.raises(AccountError) as excinfo:
        service.change_password("alice", "wrong-123", "new-pass-1")

    assert "原密码" in str(excinfo.value)
    assert service.verify_credentials("alice", "pass-123") is not None


def test_change_password_rejects_new_password_out_of_range(service):
    service.register("alice", "pass-123")

    with pytest.raises(AccountError) as excinfo:
        service.change_password("alice", "pass-123", "ab")

    assert "密码" in str(excinfo.value)
    assert service.verify_credentials("alice", "pass-123") is not None


# --- 2.5 管理员用户管理 ---


def test_admin_can_create_user_without_using_the_registration_quota(admin, service):
    account = service.create_user(admin, "bob", "pass-123")

    assert account.source == SOURCE_ADMIN
    assert account.role == ROLE_USER
    assert service.count_self_registered() == 0
    assert service.verify_credentials("bob", "pass-123") is not None


def test_admin_can_reset_password_without_the_old_one(admin, service):
    service.register("alice", "pass-123")

    service.reset_password(admin, "alice", "reset-123")

    assert service.verify_credentials("alice", "reset-123") is not None
    assert service.verify_credentials("alice", "pass-123") is None


def test_admin_can_delete_user(admin, service):
    service.register("alice", "pass-123")

    service.delete_user(admin, "alice")

    assert service.get_account("alice") is None
    assert service.verify_credentials("alice", "pass-123") is None


def test_default_admin_cannot_be_deleted(admin, service):
    with pytest.raises(AccountError) as excinfo:
        service.delete_user(admin, DEFAULT_ADMIN_USERNAME)

    assert "默认管理员" in str(excinfo.value)
    assert service.get_account(DEFAULT_ADMIN_USERNAME) is not None


def test_ordinary_user_cannot_use_the_admin_operations(service):
    actor = service.register("alice", "pass-123")
    service.register("bob", "pass-123")

    with pytest.raises(AccountPermissionError):
        service.create_user(actor, "carol", "pass-123")
    with pytest.raises(AccountPermissionError):
        service.reset_password(actor, "bob", "reset-123")
    with pytest.raises(AccountPermissionError):
        service.delete_user(actor, "bob")

    # 权限不足时不得产生任何账号变更
    assert service.get_account("carol") is None
    assert service.get_account("bob") is not None
    assert service.verify_credentials("bob", "pass-123") is not None


def test_admin_operations_report_missing_target(admin, service):
    with pytest.raises(AccountNotFoundError):
        service.reset_password(admin, "nobody", "reset-123")
    with pytest.raises(AccountNotFoundError):
        service.delete_user(admin, "nobody")


# --- 2.6 登录态令牌 ---


def test_valid_token_resolves_to_the_account(service):
    service.register("alice", "pass-123")

    token = service.issue_token("alice")

    account = service.verify_token(token)
    assert account is not None
    assert account.username == "alice"


def test_unknown_token_is_invalid(service):
    assert service.verify_token("not-a-real-token") is None
    assert service.verify_token("") is None


def test_expired_token_is_invalid(service):
    service.register("alice", "pass-123")
    token = service.issue_token("alice")
    with service._transaction() as conn:
        conn.execute(
            "UPDATE login_tokens SET expires_at = ? WHERE token = ?",
            (time.time() - 1, token),
        )

    assert service.verify_token(token) is None


def test_revoked_token_is_invalid(service):
    service.register("alice", "pass-123")
    token = service.issue_token("alice")

    service.revoke_token(token)

    assert service.verify_token(token) is None


def test_token_of_deleted_user_is_invalid(admin, service):
    service.register("alice", "pass-123")
    token = service.issue_token("alice")

    service.delete_user(admin, "alice")

    assert service.verify_token(token) is None


def test_reset_password_invalidates_all_tokens(admin, service):
    service.register("alice", "pass-123")
    token = service.issue_token("alice")

    service.reset_password(admin, "alice", "reset-123")

    assert service.verify_token(token) is None


def test_change_password_keeps_the_current_token_only(service):
    service.register("alice", "pass-123")
    other = service.issue_token("alice")
    current = service.issue_token("alice")

    service.change_password("alice", "pass-123", "new-pass-1")
    service.revoke_other_tokens("alice", current)

    assert service.verify_token(current) is not None
    assert service.verify_token(other) is None
    assert service.verify_credentials("alice", "new-pass-1") is not None


def test_expired_tokens_are_purged_on_login(service):
    service.register("alice", "pass-123")
    stale = service.issue_token("alice")
    with service._transaction() as conn:
        conn.execute(
            "UPDATE login_tokens SET expires_at = ? WHERE token = ?",
            (time.time() - 1, stale),
        )

    service.issue_token("alice")

    with service._connection() as conn:
        remaining = [
            row["token"]
            for row in conn.execute(
                "SELECT token FROM login_tokens WHERE username = ?", ("alice",)
            )
        ]
    assert stale not in remaining
    assert len(remaining) == 1