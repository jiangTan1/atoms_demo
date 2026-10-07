"""沙箱打包下载接口。

GET /api/workspace/download：把某会话沙箱内的全部文件打包为 zip 返回，保留相对目录结构。
要求登录，且目标会话必须属于当前登录用户；他人会话与不存在会话一律按不存在处理，
沙箱为空或会话不存在时返回 404 与中文提示，而不是一个空压缩包（见 design.md 决策 8）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.api.auth import CurrentUser, current_user
from app.services import workspace
from app.services.runner import get_session

router = APIRouter(prefix="/api", tags=["workspace"])


@router.get("/workspace/download")
async def download_workspace(
    request: Request,
    session_id: str,
    user: CurrentUser = Depends(current_user),
) -> Response:
    """下载该会话沙箱的整套文件；内容为 application/zip。"""
    session = await get_session(
        request.app.state.session_service,
        user_id=user.session_user_id,
        session_id=session_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在，无法下载。")

    try:
        data = workspace.zip_workspace(session_id)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if data is None:
        raise HTTPException(
            status_code=404, detail="该会话还没有生成任何文件，暂无可下载的内容。"
        )

    # 文件名只取会话标识前 8 位，保持 ASCII 且便于与页面上显示的会话 ID 对应
    filename = f"workspace-{session_id[:8]}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )