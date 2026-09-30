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