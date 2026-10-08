"""分享接口与免登录分享预览。

需要登录的接口（均校验会话归属与创建者身份）：
    POST   /api/sessions/{session_id}/shares     为某个版本生成分享链接
    GET    /api/sessions/{session_id}/shares     列出自己在该会话下创建的分享
    DELETE /api/shares/{token}                    撤销自己创建的分享

免登录、只读的分享预览：
    GET /share/{token}/                  分享页（外壳页面，用受限 iframe 嵌入应用）
    GET /share/{token}/app/              被分享版本的入口页面
    GET /share/{token}/app/{asset_path}  被分享版本内的相对资源

分享内容取自**版本快照**而不是当前沙箱，因此链接内容稳定、不随后续对话漂移，
且分享预览无需读会话（见 design.md 决策 6）。分享页不暴露会话标识与版本列表；
资源响应沿用对话内预览同一套安全头，iframe 也只授予运行所需能力
（见 specs/app-sharing/spec.md 的「分享的运行隔离」）。
"""

from __future__ import annotations

import html
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.api.auth import CurrentUser, current_user
from app.api.deps import owned_session
from app.api.preview import preview_response
from app.schemas import (
    ShareCreateRequest,
    ShareCreateResponse,
    ShareItem,
    ShareListResponse,
    ShareRevokeResponse,
)
from app.services import shares, workspace
from app.services.shares import ShareError, ShareService

router = APIRouter(prefix="/api", tags=["shares"])
share_router = APIRouter(prefix="/share", tags=["shares"])

# 分享页外壳与对话内预览使用同一套 iframe 沙箱能力：
# 只给应用运行必需的能力，绝不给 allow-same-origin（脚本读不到 Cookie 与本地存储），
# 也绝不给 allow-top-navigation（脚本不能改主站地址）——见 design.md 决策 3。
SANDBOX_ATTRS = (
    "allow-scripts allow-forms allow-modals allow-popups allow-pointer-lock"
)

# 分享页外壳的样式：只做「一块占满视口的预览区」，不引入任何外部资源
_SHELL_CSS = """
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body {
  display: flex; flex-direction: column;
  font-family: system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  background: #0f172a; color: #e2e8f0;
}
.bar {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px; font-size: 14px;
  background: #111827; border-bottom: 1px solid #1f2937;
}
.bar .dot { width: 8px; height: 8px; border-radius: 50%; background: #38bdf8; }
.bar .note { color: #94a3b8; }
iframe { flex: 1; width: 100%; border: 0; background: #ffffff; }
.msg { margin: auto; max-width: 520px; padding: 24px; text-align: center; line-height: 1.7; }
.msg h1 { font-size: 18px; margin: 0 0 8px; }
.msg p { margin: 0; color: #94a3b8; }
"""


def _service(request: Request) -> ShareService:
    return request.app.state.shares


def _shell_page(token: str) -> str:
    """分享页外壳：明确说明是只读分享，并用受限 iframe 加载应用。"""
    app_url = f"/share/{quote(token)}/app/"
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>分享的应用</title>\n"
        f"<style>{_SHELL_CSS}</style>\n"
        "</head>\n<body>\n"
        '<div class="bar"><span class="dot"></span>分享的应用'
        '<span class="note">只读预览，可正常操作应用本身</span></div>\n'
        f'<iframe src="{app_url}" sandbox="{SANDBOX_ATTRS}"'
        ' referrerpolicy="no-referrer" title="分享的应用"></iframe>\n'
        "</body>\n</html>\n"
    )


def _message_page(title: str, text: str, status_code: int) -> HTMLResponse:
    """分享链路出错时的中文提示页（访问者直接打开链接，不适合返回 JSON）。"""
    body = (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_SHELL_CSS}</style>\n"
        "</head>\n<body>\n"
        '<div class="msg">'
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(text)}</p>"
        "</div>\n</body>\n</html>\n"
    )
    return HTMLResponse(
        content=body,
        status_code=status_code,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def _missing_share() -> HTMLResponse:
    return _message_page(
        "分享不存在或已失效",
        "该分享链接不存在，或已被创建者撤销。请向分享者索取新的链接。",
        404,
    )


# --- 需要登录的分享管理接口 ---


@router.post("/sessions/{session_id}/shares", response_model=ShareCreateResponse)
async def create_share(
    session_id: str,
    payload: ShareCreateRequest,
    request: Request,
    user: CurrentUser = Depends(current_user),
    session=Depends(owned_session),
) -> ShareCreateResponse:
    """为指定版本生成公开只读分享链接。"""
    try:
        record = _service(request).create(
            session_id, payload.version_id, user.session_user_id
        )
    except ShareError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    item = ShareItem(
        token=record["token"],
        version_id=record["version_id"],
        created_at=record["created_at"],
        url=shares.share_url(record["token"]),
    )
    return ShareCreateResponse(
        share=item,
        message=f"已为版本 {record['version_id']} 生成分享链接，复制后即可发给任何人打开。",
    )


@router.get("/sessions/{session_id}/shares", response_model=ShareListResponse)
async def list_shares(
    session_id: str,
    request: Request,
    user: CurrentUser = Depends(current_user),
    session=Depends(owned_session),
) -> ShareListResponse:
    """列出自己在该会话下创建的分享（按创建时间倒序）。"""
    records = _service(request).list_for(user.session_user_id, session_id)
    return ShareListResponse(
        shares=[
            ShareItem(
                token=record["token"],
                version_id=record["version_id"],
                created_at=record["created_at"],
                url=shares.share_url(record["token"]),
            )
            for record in records
        ]
    )


@router.delete("/shares/{token}", response_model=ShareRevokeResponse)
async def revoke_share(
    token: str,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> ShareRevokeResponse:
    """撤销自己创建的分享；撤销后原链接立即失效。"""
    try:
        key = _service(request).revoke(token, user.session_user_id)
    except ShareError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ShareRevokeResponse(token=key, message="已撤销该分享链接，原链接不再可用。")


# --- 免登录、只读的分享预览 ---


@share_router.get("/{token}/", response_class=HTMLResponse)
async def share_shell(token: str, request: Request) -> Response:
    """分享页外壳：不暴露会话信息，只把被分享版本放进受限 iframe。"""
    if _service(request).resolve(token) is None:
        return _missing_share()
    return HTMLResponse(
        content=_shell_page(token),
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def _shared_snapshot(request: Request, token: str):
    """把 token 解析为被分享版本的快照目录；不存在或快照缺失时返回 None。"""
    record = _service(request).resolve(token)
    if record is None:
        return None
    try:
        target = shares.snapshot_dir(record["session_id"], record["version_id"])
    except ShareError:
        return None
    return target if target.is_dir() else None


@share_router.get("/{token}/app/")
async def share_entry(token: str, request: Request) -> Response:
    """返回被分享版本的入口页面；缺少入口文件时给出中文提示页。"""
    target = _shared_snapshot(request, token)
    if target is None:
        return _missing_share()

    path = workspace.dir_entry_path(target)
    if path is None:
        return _message_page(
            "该版本没有可预览的应用",
            "被分享的版本内缺少入口文件 index.html，无法呈现应用内容。",
            404,
        )
    return preview_response(
        path.read_bytes(), workspace.guess_content_type(workspace.ENTRY_FILE_NAME)
    )


@share_router.get("/{token}/app/{asset_path:path}")
async def share_asset(token: str, asset_path: str, request: Request) -> Response:
    """返回被分享版本内的相对资源；路径逃逸与隐藏文件一律拒绝。"""
    target = _shared_snapshot(request, token)
    if target is None:
        return _missing_share()

    try:
        data, content_type = workspace.read_dir_asset(target, asset_path)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return preview_response(data, content_type)