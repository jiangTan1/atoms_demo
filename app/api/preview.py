"""应用预览接口。

GET /api/sessions/{session_id}/preview-token   为当前使用者名下的会话签发预览票据
GET /preview/{session_id}/{token}/             返回该会话沙箱的入口页面 index.html
GET /preview/{session_id}/{token}/{asset_path} 返回沙箱内按相对路径定位的静态资源

把会话沙箱当作一个静态站点挂在 `/preview/<会话标识>/<票据>/` 下，入口页面中以相对路径引用的
样式、脚本、图片因此无需改写路径即可加载（见 design.md 决策 2、11）。

票据放在**路径**而不是查询串里，是必要的一步：预览 iframe 处在不透明源，其子资源请求被浏览器
视为跨站，登录态 Cookie 不会跟随（`SameSite=Lax`），会得到 401，并在 script / stylesheet 目的下
被 Chrome 的 ORB 拦掉，使预览里样式与脚本全部失效。相对路径会自动继承同前缀的票据，
因此子资源无需 Cookie 即可取用（缘由与实现见 `app/services/preview_token.py`）。

票据只能由已登录、且目标会话属于本人的使用者换取（`owned_session`：未登录 401、他人会话按
不存在处理）。响应统一带安全响应头（禁止内容嗅探、限制资源来源、禁用缓存），并拒绝隐藏文件
（见 design.md 决策 3）。分享预览沿用同一套响应头，故这里的构造函数对外公开。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.deps import owned_session
from app.schemas import PreviewTokenResponse
from app.services import preview_token, workspace

router = APIRouter(prefix="/preview", tags=["preview"])
token_router = APIRouter(prefix="/api/sessions", tags=["preview"])

# 票据无效、过期或与路径中的会话不匹配时的提示（前端据此提示重新打开预览）
INVALID_TOKEN_DETAIL = "预览链接无效或已过期，请在对话界面重新打开预览。"

# 预览响应的统一安全头（分享预览沿用同一套，见 design.md 决策 3、6）：
# - nosniff：按服务器给出的内容类型解释，不根据内容猜类型；
# - CSP：允许应用自身所需的脚本与资源（含内联与 eval），但断掉对外连接
#   （connect-src 'none' 阻断 fetch/XHR，使应用无法代表使用者调用主站接口），
#   同时禁用 object 与 <base>；不设 frame-ancestors——预览文档处在不透明源中，
#   `'self'` 会误伤同源父页面，而预览本就需要被主站 iframe 嵌入；
# - no-store：预览呈现的应始终是沙箱当前内容，不做缓存。
PREVIEW_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src * data: blob: 'unsafe-inline' 'unsafe-eval'; "
        "connect-src 'none'; object-src 'none'; base-uri 'none'"
    ),
}


def preview_response(data: bytes, content_type: str) -> Response:
    """构造带预览安全头的资源响应，供对话内预览与分享预览共用。"""
    return Response(content=data, media_type=content_type, headers=PREVIEW_HEADERS)


def no_entry_detail(session_id: str) -> str:
    """缺少可预览应用时的中文说明：区分空沙箱与「有文件但没有入口」。"""
    if workspace.list_files(session_id):
        return (
            "该会话还没有可预览的应用：沙箱内缺少入口文件 index.html。"
            "应用需包含入口文件才能预览，可在对话中让智能体补上入口文件。"
        )
    return (
        "该会话还没有可预览的应用，请先在对话中描述你想要的网页应用，"
        "让智能体生成后再预览。"
    )


def preview_path(session_id: str, token: str) -> str:
    """预览入口的相对地址；页面内的相对资源会自动继承同一前缀。"""
    return f"/preview/{session_id}/{token}/"


def _require_token(session_id: str, token: str) -> None:
    """校验路径内的预览票据；缺失、过期或挪用到别的会话一律拒绝。"""
    if not preview_token.verify(session_id, token):
        raise HTTPException(status_code=403, detail=INVALID_TOKEN_DETAIL)


@token_router.get("/{session_id}/preview-token", response_model=PreviewTokenResponse)
async def issue_preview_token(
    session_id: str,
    session=Depends(owned_session),
) -> PreviewTokenResponse:
    """为当前登录使用者名下的会话签发预览票据，并连同入口地址一起返回。

    缺少入口文件时按 404 处理并给出中文提示，使前端一次请求即可区分「尚无应用」与「已可预览」。
    """
    if workspace.entry_path(session_id) is None:
        raise HTTPException(status_code=404, detail=no_entry_detail(session_id))
    token, expires_in = preview_token.issue(session_id)
    return PreviewTokenResponse(
        token=token, url=preview_path(session_id, token), expires_in=expires_in
    )


@router.get("/{session_id}/{token}/")
async def preview_entry(session_id: str, token: str) -> Response:
    """返回该会话沙箱的入口页面；缺少入口文件时给出明确提示而不是空白页。"""
    _require_token(session_id, token)
    path = workspace.entry_path(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail=no_entry_detail(session_id))
    return preview_response(
        path.read_bytes(), workspace.guess_content_type(workspace.ENTRY_FILE_NAME)
    )


@router.get("/{session_id}/{token}/{asset_path:path}")
async def preview_asset(session_id: str, token: str, asset_path: str) -> Response:
    """按相对路径返回沙箱内的单个静态资源，内容类型按扩展名判定。

    路径安全与隐藏文件拒绝都在 `workspace.read_asset` 内完成；不存在的资源返回 404，
    使入口页面引用的个别资源缺失不至于让整页预览不可用。
    """
    _require_token(session_id, token)
    try:
        data, content_type = workspace.read_asset(session_id, asset_path)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return preview_response(data, content_type)