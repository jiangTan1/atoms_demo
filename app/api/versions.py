"""版本接口。

GET  /api/sessions/{session_id}/versions                          列出该会话的版本（时间倒序）
POST /api/sessions/{session_id}/versions/{version_id}/rollback    把沙箱恢复到指定版本

两个路由都要求登录，且目标会话必须属于当前登录用户；他人会话与不存在的版本
一律按不存在处理并给出中文提示（见 specs/app-versions/spec.md）。
鉴权与归属校验由 `owned_session` 依赖完成（未登录返回 401）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import owned_session
from app.schemas import RollbackResponse, VersionItem, VersionListResponse
from app.services import versions

router = APIRouter(prefix="/api", tags=["versions"])


@router.get("/sessions/{session_id}/versions", response_model=VersionListResponse)
async def read_versions(
    session_id: str,
    session=Depends(owned_session),
) -> VersionListResponse:
    """按时间倒序返回该会话的全部版本；尚无版本时返回空列表。"""
    records = versions.list_versions(session_id)
    return VersionListResponse(
        session_id=session_id,
        versions=[VersionItem(**record) for record in records],
    )


@router.post(
    "/sessions/{session_id}/versions/{version_id}/rollback",
    response_model=RollbackResponse,
)
async def rollback_version(
    session_id: str,
    version_id: str,
    request: Request,
    session=Depends(owned_session),
) -> RollbackResponse:
    """把沙箱恢复到指定版本；回滚前先留存当前内容，因此回滚可逆。"""
    try:
        result = versions.rollback(session_id, version_id, request.app.state.settings)
    except versions.VersionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return RollbackResponse(
        session_id=session_id,
        version_id=result["version_id"],
        preserved_version_id=result["preserved_version_id"],
        message=f"已回滚到版本 {result['version_id']}，可继续对话修改或在版本列表中回到回滚前。",
    )