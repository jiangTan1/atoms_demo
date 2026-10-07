"""配置层单元测试：完整配置 / 缺 api_key / base_url 无版本路径 三个用例。"""

from __future__ import annotations

import pytest

from app.config import ConfigError, load_settings

BASE_ENV = {
    "LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "LLM_MODEL": "glm-4.5-flash",
    "LLM_API_KEY": "sk-test-1234567890",
    "APP_HOST": "127.0.0.1",
    "APP_PORT": "8000",
    "SESSION_BACKEND": "memory",
}


def test_full_config_is_loaded():
    settings = load_settings(BASE_ENV)

    assert settings.llm_base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert settings.llm_model == "glm-4.5-flash"
    assert settings.llm_api_key == "sk-test-1234567890"
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8000
    assert settings.session_backend == "memory"


def test_missing_api_key_reports_the_key_name():
    env = {k: v for k, v in BASE_ENV.items() if k != "LLM_API_KEY"}

    with pytest.raises(ConfigError) as excinfo:
        load_settings(env)

    assert excinfo.value.key == "LLM_API_KEY"
    assert "LLM_API_KEY" in str(excinfo.value)


def test_base_url_without_version_path_is_rejected():
    env = {**BASE_ENV, "LLM_BASE_URL": "https://open.bigmodel.cn/api/paas"}

    with pytest.raises(ConfigError) as excinfo:
        load_settings(env)

    assert excinfo.value.key == "LLM_BASE_URL"


def test_invalid_port_is_rejected():
    env = {**BASE_ENV, "APP_PORT": "not-a-port"}

    with pytest.raises(ConfigError) as excinfo:
        load_settings(env)

    assert excinfo.value.key == "APP_PORT"


def test_workspace_quotas_fall_back_to_defaults():
    settings = load_settings(BASE_ENV)

    assert settings.workspace_max_file_bytes == 262144
    assert settings.workspace_max_files == 200
    assert settings.workspace_max_total_bytes == 10485760


def test_workspace_quotas_accept_explicit_values():
    env = {
        **BASE_ENV,
        "WORKSPACE_MAX_FILE_BYTES": "1024",
        "WORKSPACE_MAX_FILES": "5",
        "WORKSPACE_MAX_TOTAL_BYTES": "2048",
    }

    settings = load_settings(env)

    assert settings.workspace_max_file_bytes == 1024
    assert settings.workspace_max_files == 5
    assert settings.workspace_max_total_bytes == 2048


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("WORKSPACE_MAX_FILE_BYTES", "0"),
        ("WORKSPACE_MAX_FILES", "-1"),
        ("WORKSPACE_MAX_TOTAL_BYTES", "10MB"),
    ],
)
def test_invalid_workspace_quota_reports_the_key_name(key, value):
    env = {**BASE_ENV, key: value}

    with pytest.raises(ConfigError) as excinfo:
        load_settings(env)

    assert excinfo.value.key == key
    assert key in str(excinfo.value)


def test_auth_cookie_secure_defaults_to_false():
    settings = load_settings(BASE_ENV)

    assert settings.auth_cookie_secure is False


def test_auth_cookie_secure_accepts_explicit_true():
    settings = load_settings({**BASE_ENV, "AUTH_COOKIE_SECURE": "true"})

    assert settings.auth_cookie_secure is True


@pytest.mark.parametrize("value", ["maybe", "2", "tru e"])
def test_invalid_auth_cookie_secure_reports_the_key_name(value):
    env = {**BASE_ENV, "AUTH_COOKIE_SECURE": value}

    with pytest.raises(ConfigError) as excinfo:
        load_settings(env)

    assert excinfo.value.key == "AUTH_COOKIE_SECURE"
    assert "AUTH_COOKIE_SECURE" in str(excinfo.value)