"""ADK Agent 定义。

定义 LlmAgent 并导出 root_agent，供 Runner 使用。
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.agent.model import build_model
from app.agent.prompt import build_instruction
from app.agent.tools import FILE_TOOLS
from app.config import get_settings

AGENT_NAME = "code_assistant"

root_agent = LlmAgent(
    name=AGENT_NAME,
    description="网页应用生成智能体：根据自然语言需求生成与迭代修改可直接运行的网页应用。",
    model=build_model(get_settings()),
    instruction=build_instruction(),
    tools=list(FILE_TOOLS),
)