"""接口层公共依赖。

提供「会话归属校验」依赖：预览、版本与分享接口都要确认目标会话属于当前登录用户，
不属于自己或不存在的一律按不存在处理（404），不暴露其是否存在。

归属一律取自登录态（`user:<登录用户名>`），请求里携带的任何归属信息都不参与判定
（见 specs/access-control/spec.md 的「会话归属由登录态决定」）。
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.api.auth import CurrentUser, current_user
from app.services.runner import get_session


async def owned_session(
    session_id: str,
    request: Request,
    user: CurrentUser = Depends(current_user),
):
    """校验路径中的会话属于当前登录用户，返回该会话；否则 404 与中文提示。"""
    session = await get_session(
        request.app.state.session_service,
        user_id=user.session_user_id,
        session_id=session_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return session