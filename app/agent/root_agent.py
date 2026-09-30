"""ADK Agent 定义。

定义 LlmAgent 并导出 root_agent，供 Runner 使用。
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.agent.model import build_model
from app.agent.prompt import build_instruction
from app.config import get_settings

AGENT_NAME = "code_assistant"

root_agent = LlmAgent(
    name=AGENT_NAME,
    description="面向开发者的代码助手：代码生成、代码解释、重构与优化。",
    model=build_model(get_settings()),
    instruction=build_instruction(),
)