"""提示词装配。

加载 prompts/system.md，并在使用者未指定目标语言时追加语言推断与澄清规则。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "system.md"

NO_TARGET_LANGUAGE_RULE = """
## 本轮语言约束

本轮使用者未指定目标语言。请按问题语义推断最合适的语言；若语义不足以确定语言，
先用一句话向使用者确认目标语言，不要默认输出某一种语言。
"""

TARGET_LANGUAGE_RULE = """
## 本轮语言约束

本轮使用者指定目标语言为 {language}。所有代码必须使用该语言输出，
代码块的语言标识也要与之一致；若该语言不适合此问题，先说明原因再给出最接近的实现。
"""


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """读取 system.md 原文。"""
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_instruction(target_language: str | None = None) -> str:
    """拼装 Agent 指令：system.md + 本轮语言规则。"""
    rule = (
        TARGET_LANGUAGE_RULE.format(language=target_language)
        if target_language
        else NO_TARGET_LANGUAGE_RULE
    )
    return f"{load_system_prompt()}\n\n{rule.strip()}\n"