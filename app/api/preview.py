"""应用预览接口。

GET /preview/{session_id}/                返回该会话沙箱的入口页面 index.html
GET /preview/{session_id}/{asset_path}    返回沙箱内按相对路径定位的静态资源

把会话沙箱当作一个静态站点挂在 `/preview/<会话标识>/` 下，入口页面中以相对路径引用的
样式、脚本、图片因此无需改写路径即可加载（见 design.md 决策 2）。两个路由都要求登录并
校验会话归属（由 `owned_session` 完成：未登录 401、他人会话按不存在处理）；
响应统一带安全响应头（禁止内容嗅探、限制资源来源、禁用缓存），并拒绝隐藏文件
（见 design.md 决策 3）。分享预览沿用同一套响应头，故这里的构造函数对外公开。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.deps import owned_session
from app.services import workspace

router = APIRouter(prefix="/preview", tags=["preview"])

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


@router.get("/{session_id}/")
async def preview_entry(
    session_id: str,
    session=Depends(owned_session),
) -> Response:
    """返回该会话沙箱的入口页面；缺少入口文件时给出明确提示而不是空白页。"""
    path = workspace.entry_path(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail=no_entry_detail(session_id))
    return preview_response(
        path.read_bytes(), workspace.guess_content_type(workspace.ENTRY_FILE_NAME)
    )


@router.get("/{session_id}/{asset_path:path}")
async def preview_asset(
    session_id: str,
    asset_path: str,
    session=Depends(owned_session),
) -> Response:
    """按相对路径返回沙箱内的单个静态资源，内容类型按扩展名判定。

    路径安全与隐藏文件拒绝都在 `workspace.read_asset` 内完成；不存在的资源返回 404，
    使入口页面引用的个别资源缺失不至于让整页预览不可用。
    """
    try:
        data, content_type = workspace.read_asset(session_id, asset_path)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return preview_response(data, content_type)