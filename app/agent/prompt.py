"""提示词装配。

加载 prompts/system.md 作为 Agent 指令。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "system.md"


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """读取 system.md 原文。"""
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_instruction() -> str:
    """拼装 Agent 指令。

    目标语言与澄清轮次每轮都可能变化，而 instruction 是模块级静态值（进程内不变），
    因此这两类信息由用户消息前缀承载，见 app/services/chat.py 的 compose_user_message()。
    """
    return f"{load_system_prompt()}\n"