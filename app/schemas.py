"""接口数据模型。

对话请求、会话响应与 SSE 帧的 pydantic 定义，帧协议见 design.md 决策 4：

    {"type": "text",  "data": "<增量文本>", "partial": true|false}
    {"type": "error", "data": {"code": "...", "message": "..."}}
    {"type": "done",  "data": {"session_id": "...", "message_id": "..."}}

历史会话相关模型用于 GET /api/sessions 与 GET /api/sessions/{session_id}/messages。
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field, field_validator

# 目标语言：对外取值 -> 提示词与界面中使用的名称
TARGET_LANGUAGES = {
    "java": "Java",
    "python": "Python",
    "csharp": "C#",
    "cpp": "C++",
    "html": "HTML",
    "javascript": "JavaScript",
}

DEFAULT_USER_ID = "web-user"


class ChatRequest(BaseModel):
    """一次对话请求。session_id 为空时由服务端新建会话。"""

    message: str = Field(min_length=1, description="使用者的自然语言问题或代码片段")
    session_id: str | None = None
    user_id: str = Field(default=DEFAULT_USER_ID, min_length=1)
    target_language: str | None = None

    @field_validator("message", "user_id")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("target_language")
    @classmethod
    def _check_language(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        key = value.strip().lower()
        if key not in TARGET_LANGUAGES:
            raise ValueError(
                f"不支持的目标语言 {value!r}，可选：{'、'.join(TARGET_LANGUAGES)}"
            )
        return key


class SessionCreateRequest(BaseModel):
    user_id: str = Field(default=DEFAULT_USER_ID, min_length=1)


class SessionResponse(BaseModel):
    session_id: str
    user_id: str


# --- 历史会话 ---


class HistoryMessage(BaseModel):
    """一条已还原的历史消息。"""

    role: Literal["user", "assistant"]
    text: str


class SessionMessagesResponse(BaseModel):
    session_id: str
    user_id: str
    messages: list[HistoryMessage]


class SessionSummary(BaseModel):
    """历史会话列表条目。updated_at 为 epoch 秒，由前端做本地化展示。"""

    session_id: str
    title: str
    updated_at: float
    message_count: int


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


# --- SSE 帧 ---


class TextFrame(BaseModel):
    type: Literal["text"] = "text"
    data: str
    partial: bool


class ErrorData(BaseModel):
    code: str
    message: str


class ErrorFrame(BaseModel):
    type: Literal["error"] = "error"
    data: ErrorData


class DoneData(BaseModel):
    session_id: str
    message_id: str


class DoneFrame(BaseModel):
    type: Literal["done"] = "done"
    data: DoneData


Frame = Union[TextFrame, ErrorFrame, DoneFrame]