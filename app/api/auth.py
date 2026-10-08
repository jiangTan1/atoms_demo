"""认证接口与鉴权依赖。

`/api/auth` 下的注册、登录、退出登录、修改自己的密码、当前身份查询，
以及仅管理员可用的用户管理（新增 / 重置密码 / 删除）；
另提供 `current_user` / `require_admin` 两个依赖，供 chat、sessions、workspace 声明。

对应 specs/access-control/spec.md 与 specs/user-accounts/spec.md，
设计依据见本变更 design.md 决策 2、3、4：

- 登录态是服务端随机令牌 + HttpOnly Cookie，改密吊销只需删表记录。
- 鉴权用 FastAPI 依赖注入：哪些接口要登录在签名里可见，不维护路径白名单。
- 会话与沙箱归属统一用 `user:<登录用户名>`，与既有匿名会话的 `web-user` 不可能碰撞。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.schemas import (
    AdminResetPasswordRequest,
    AdminUserRequest,
    AuthMessage,
    ChangePasswordRequest,
    IdentityResponse,
    LoginRequest,
    RegisterRequest,
)
from app.services.accounts import (
    ROLE_ADMIN,
    TOKEN_TTL_SECONDS,
    Account,
    AccountError,
    AccountNotFoundError,
    AccountPermissionError,
    AccountService,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "code_assistant_token"

UNAUTHORIZED_DETAIL = "登录状态无效或已过期，请重新登录。"
BAD_CREDENTIALS_DETAIL = "用户名或密码错误。"
PERMISSION_DETAIL = "该操作仅管理员可用。"


def session_user_id(username: str) -> str:
    """会话与沙箱的归属标识。

    固定加 `user:` 前缀，使登录用户的标识永远不等于认证改造前匿名会话用的 `web-user`，
    「既有匿名会话不再展示」由此自然成立，且不需要迁移数据（见 design.md 决策 4）。
    """
    return f"user:{username}"


@dataclass(frozen=True)
class CurrentUser:
    """一次请求的登录身份。token 供退出登录与改密时定位当前登录态。"""

    username: str
    role: str
    token: str

    @property
    def session_user_id(self) -> str:
        return session_user_id(self.username)


def _service(request: Request) -> AccountService:
    return request.app.state.accounts


def _http_error(exc: AccountError) -> HTTPException:
    """账号服务的异常到 HTTP 状态的映射，消息原样透出（均为中文）。"""
    if isinstance(exc, AccountPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, AccountNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


async def current_user(request: Request) -> CurrentUser:
    """从 Cookie 取登录态令牌并校验；缺失或无效一律 401 与中文提示。"""
    token = request.cookies.get(COOKIE_NAME, "")
    account = _service(request).verify_token(token)
    if account is None:
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
    return CurrentUser(username=account.username, role=account.role, token=token)


async def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """在已登录的基础上要求管理员角色。"""
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail=PERMISSION_DETAIL)
    return user


def _actor(service: AccountService, user: CurrentUser) -> Account:
    """账号服务的管理操作需要 Account 作为操作者。"""
    account = service.get_account(user.username)
    if account is None:
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
    return account


def _set_token_cookie(request: Request, response: Response, token: str) -> None:
    """下发登录态 Cookie：HttpOnly、SameSite=Lax、Path=/，有效期 1 天。"""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=TOKEN_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
        secure=bool(request.app.state.settings.auth_cookie_secure),
    )


# --- 无需登录的接口 ---


@router.post("/register", response_model=AuthMessage)
async def register(payload: RegisterRequest, request: Request) -> AuthMessage:
    """自助注册：一律生成普通用户，受 99 个普通用户的上限约束。"""
    try:
        account = _service(request).register(payload.username, payload.password)
    except AccountError as exc:
        raise _http_error(exc) from exc
    return AuthMessage(message=f"注册成功，请使用 {account.username} 登录。")


@router.post("/login", response_model=IdentityResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response
) -> IdentityResponse:
    """登录：凭据正确时签发登录态令牌并下发 Cookie。"""
    service = _service(request)
    account = service.verify_credentials(payload.username, payload.password)
    if account is None:
        raise HTTPException(status_code=401, detail=BAD_CREDENTIALS_DETAIL)
    _set_token_cookie(request, response, service.issue_token(account.username))
    return IdentityResponse(username=account.username, role=account.role)


@router.get("/me", response_model=IdentityResponse)
async def read_identity(user: CurrentUser = Depends(current_user)) -> IdentityResponse:
    """当前身份；未登录返回 401，供前端做页面加载时的登录态门控。"""
    return IdentityResponse(username=user.username, role=user.role)


@router.post("/logout", response_model=AuthMessage)
async def logout(
    request: Request, response: Response, user: CurrentUser = Depends(current_user)
) -> AuthMessage:
    """退出登录：吊销当前登录态并清除 Cookie。"""
    _service(request).revoke_token(user.token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return AuthMessage(message="已退出登录。")


@router.post("/password", response_model=AuthMessage)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> AuthMessage:
    """修改自己的密码；成功后吊销该用户的其他登录态，保留当前这一个。"""
    service = _service(request)
    try:
        service.change_password(user.username, payload.old_password, payload.new_password)
    except AccountError as exc:
        raise _http_error(exc) from exc
    service.revoke_other_tokens(user.username, user.token)
    return AuthMessage(message="密码已修改，其他已登录的会话已失效。")


# --- 仅管理员可用 ---


@router.post("/users", response_model=AuthMessage)
async def admin_create_user(
    payload: AdminUserRequest,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> AuthMessage:
    """管理员新增用户：不占用自助注册的 99 个名额。"""
    service = _service(request)
    try:
        account = service.create_user(_actor(service, admin), payload.username, payload.password)
    except AccountError as exc:
        raise _http_error(exc) from exc
    return AuthMessage(message=f"已新增用户 {account.username}。")


@router.post("/users/{username}/password", response_model=AuthMessage)
async def admin_reset_password(
    username: str,
    payload: AdminResetPasswordRequest,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> AuthMessage:
    """管理员重置任意用户的密码（无需原密码），该用户全部登录态随即失效。"""
    service = _service(request)
    try:
        service.reset_password(_actor(service, admin), username, payload.password)
    except AccountError as exc:
        raise _http_error(exc) from exc
    return AuthMessage(message=f"已重置用户 {username} 的密码。")


@router.delete("/users/{username}", response_model=AuthMessage)
async def admin_delete_user(
    username: str,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> AuthMessage:
    """管理员删除用户；内置管理员（`source='system'`）不可删除。"""
    service = _service(request)
    try:
        service.delete_user(_actor(service, admin), username)
    except AccountError as exc:
        raise _http_error(exc) from exc
    return AuthMessage(message=f"已删除用户 {username}。")