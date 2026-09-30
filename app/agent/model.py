"""模型接入层。

用 ADK 的 LiteLlm 包装任意 OpenAI 兼容端点：

    LiteLlm(model="openai/<LLM_MODEL>",
            api_base=<LLM_BASE_URL>,
            api_key=<LLM_API_KEY>)

端点地址、模型标识与凭据全部来自配置层，本模块不含任何硬编码。
LiteLLM 支持由 google-adk[extensions] 提供。
"""

from __future__ import annotations

from google.adk.models.lite_llm import LiteLlm

from app.config import Settings

# LiteLlm 用模型串前缀决定走哪个 provider 适配器，OpenAI 兼容端点统一加此前缀
OPENAI_PREFIX = "openai/"


def build_model(settings: Settings) -> LiteLlm:
    """按配置构建模型对象。"""
    return LiteLlm(
        model=f"{OPENAI_PREFIX}{settings.llm_model}",
        api_base=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )