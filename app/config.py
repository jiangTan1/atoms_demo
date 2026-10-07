"""配置层。

从环境变量与 .env 读取模型接入配置与运行参数，启动时做必填校验。

对应 specs/model-integration/spec.md 的「OpenAI 兼容端点接入」与「配置校验与可诊断错误」。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# ADK 中的应用标识，会话与 Runner 都以它归属
APP_NAME = "code-assistant"

# base_url 需要带版本路径（/v1、/v4、/v1beta 等），否则端点多会返回 404
_VERSION_PATH_RE = re.compile(r"/v\d+[a-z0-9.]*$", re.IGNORECASE)

# .env.example 里的占位值，直接启动会在端点侧报鉴权失败，这里提前拦下
PLACEHOLDER_VALUES = frozenset({"replace-me", "replace_me", "your-api-key", "changeme"})

SESSION_BACKENDS = ("memory", "sqlite")

# 会话默认落盘：页面刷新与服务重启后仍能找回历史对话
DEFAULT_SESSION_BACKEND = "sqlite"

# 会话沙箱配额默认值（见 specs/file-workspace/spec.md 的「沙箱配额限制」）：
# 单文件 256 KB、单会话 200 个文件、单会话总占用 10 MB
DEFAULT_WORKSPACE_MAX_FILE_BYTES = 262144
DEFAULT_WORKSPACE_MAX_FILES = 200
DEFAULT_WORKSPACE_MAX_TOTAL_BYTES = 10485760


class ConfigError(RuntimeError):
    """配置缺失或格式非法。消息中始终包含出问题的配置项名称。"""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"配置项 {key} {reason}")


@dataclass(frozen=True)
class Settings:
    """一次启动所需的全部配置。"""

    llm_base_url: str
    llm_model: str
    llm_api_key: str
    app_host: str
    app_port: int
    session_backend: str
    workspace_max_file_bytes: int
    workspace_max_files: int
    workspace_max_total_bytes: int

    @property
    def api_base(self) -> str:
        """LiteLLM 需要的端点地址（与 llm_base_url 同值，语义化别名）。"""
        return self.llm_base_url


def _required(env: Mapping[str, str], key: str) -> str:
    value = (env.get(key) or "").strip()
    if not value:
        raise ConfigError(key, "缺失，请在 .env 中填写（可参考 .env.example）")
    if key == "LLM_API_KEY" and value.lower() in PLACEHOLDER_VALUES:
        raise ConfigError(key, f"仍是占位值 {value!r}，请替换为真实的访问凭据")
    return value


def _validate_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError("LLM_BASE_URL", f"不是合法的 http(s) 地址：{value!r}")
    if not _VERSION_PATH_RE.search(parsed.path.rstrip("/")):
        raise ConfigError(
            "LLM_BASE_URL",
            f"缺少版本路径（如 /v1、/v4），当前为 {value!r}，直接调用会得到 404",
        )
    return value.rstrip("/")


def _validate_port(env: Mapping[str, str]) -> int:
    raw = (env.get("APP_PORT") or "").strip() or "8000"
    try:
        port = int(raw)
    except ValueError:
        raise ConfigError("APP_PORT", f"不是合法整数：{raw!r}") from None
    if not 1 <= port <= 65535:
        raise ConfigError("APP_PORT", f"超出 1-65535 范围：{port}")
    return port


def _validate_session_backend(env: Mapping[str, str]) -> str:
    backend = (env.get("SESSION_BACKEND") or "").strip().lower() or DEFAULT_SESSION_BACKEND
    if backend not in SESSION_BACKENDS:
        raise ConfigError(
            "SESSION_BACKEND", f"取值 {backend!r} 不支持，可选：{'、'.join(SESSION_BACKENDS)}"
        )
    return backend


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    """读取可选的配额配置项：缺省取默认值，非正整数时报错并点名配置项。"""
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(key, f"不是合法整数：{raw!r}") from None
    if value <= 0:
        raise ConfigError(key, f"必须是正整数，当前为 {value}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """读取并校验配置；env 为 None 时先加载 .env 再读进程环境变量。"""
    if env is None:
        load_dotenv(ENV_FILE, override=False)
        env = os.environ
    return Settings(
        llm_base_url=_validate_base_url(_required(env, "LLM_BASE_URL")),
        llm_model=_required(env, "LLM_MODEL"),
        llm_api_key=_required(env, "LLM_API_KEY"),
        app_host=(env.get("APP_HOST") or "").strip() or "127.0.0.1",
        app_port=_validate_port(env),
        session_backend=_validate_session_backend(env),
        workspace_max_file_bytes=_positive_int(
            env, "WORKSPACE_MAX_FILE_BYTES", DEFAULT_WORKSPACE_MAX_FILE_BYTES
        ),
        workspace_max_files=_positive_int(
            env, "WORKSPACE_MAX_FILES", DEFAULT_WORKSPACE_MAX_FILES
        ),
        workspace_max_total_bytes=_positive_int(
            env, "WORKSPACE_MAX_TOTAL_BYTES", DEFAULT_WORKSPACE_MAX_TOTAL_BYTES
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内共享的配置单例，首次调用时校验，失败即抛出 ConfigError。"""
    return load_settings()