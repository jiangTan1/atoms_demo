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


class ChatRequest(BaseModel):
    """一次对话请求。session_id 为空时由服务端新建会话。

    归属者不再由客户端指定：会话归属一律取自登录态（见 specs/session-history/spec.md
    的「会话归属由登录态决定」）。请求里若仍带 user_id，会被模型忽略。
    """

    message: str = Field(min_length=1, description="使用者的自然语言问题或代码片段")
    session_id: str | None = None
    target_language: str | None = None

    @field_validator("message")
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
    """新建会话请求体。

    归属者取自登录态，请求体不再携带任何归属信息；保留该模型是为了维持
    `POST /api/sessions` 可带空请求体的既有形态，多余的字段一律被忽略。
    """


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


# --- 认证 ---
#
# 用户名与密码的长度约束由账号服务负责，以保证拒绝时的提示为中文且一致；
# 这里的模型只保证字段存在，不做过早的格式拒绝。


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class AdminUserRequest(BaseModel):
    """管理员新增用户。"""

    username: str
    password: str


class AdminResetPasswordRequest(BaseModel):
    """管理员重置指定用户的密码（无需原密码）。"""

    password: str


class IdentityResponse(BaseModel):
    """当前登录身份。"""

    username: str
    role: str


class AuthMessage(BaseModel):
    """认证类操作的文字反馈。"""

    message: str


# --- 应用版本 ---


class VersionItem(BaseModel):
    """一条版本记录。created_at 为 epoch 秒，由前端做本地化展示。"""

    version_id: str
    created_at: float


class VersionListResponse(BaseModel):
    session_id: str
    versions: list[VersionItem]


class RollbackResponse(BaseModel):
    """回滚结果。preserved_version_id 为回滚前内容被留存成的版本（沙箱为空时为 None）。"""

    session_id: str
    version_id: str
    preserved_version_id: str | None = None
    message: str


# --- 应用分享 ---


class ShareCreateRequest(BaseModel):
    """为某个版本生成公开只读分享。"""

    version_id: str


class ShareItem(BaseModel):
    """一条分享记录。url 为可直接打开的相对地址。"""

    token: str
    version_id: str
    created_at: float
    url: str


class ShareCreateResponse(BaseModel):
    share: ShareItem
    message: str


class ShareListResponse(BaseModel):
    shares: list[ShareItem]


class ShareRevokeResponse(BaseModel):
    token: str
    message: str


class ShareMessage(BaseModel):
    """分享访问失败时的文字反馈（免登录路由不返回结构化错误）。"""

    message: str


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