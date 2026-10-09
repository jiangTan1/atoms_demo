"""预置示例应用接口。

`GET /api/examples` 列出内置示例；`POST /api/examples/apply` 选用示例：服务端创建一个
归属于当前登录使用者的新会话，并把该示例的模板复制进其沙箱，返回 session_id
（见 specs/example-apps/spec.md）。

两条路由都要求登录；未知示例返回 404，复制失败返回 500 且回退刚创建的空会话，
不留下「有会话但沙箱为空或残缺」的状态。这是「新建会话惰性创建」约定的唯一例外：
选择示例必须立刻有沙箱可预览（见 design.md 决策 6）。
"""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import CurrentUser, current_user
from app.schemas import (
    ExampleApplyRequest,
    ExampleApplyResponse,
    ExampleItem,
    ExampleListResponse,
)
from app.services import examples as examples_service
from app.services import workspace
from app.services.runner import create_session, delete_session

router = APIRouter(prefix="/api", tags=["examples"])


@router.get("/examples", response_model=ExampleListResponse)
async def list_examples(
    user: CurrentUser = Depends(current_user),
) -> ExampleListResponse:
    """列出内置示例的标识、名称与一句话描述，不请求模型。"""
    try:
        examples = examples_service.load_examples()
    except examples_service.ExampleError as exc:
        raise HTTPException(status_code=500, detail=f"示例清单不可用：{exc}") from exc

    return ExampleListResponse(
        examples=[
            ExampleItem(id=item.id, name=item.name, description=item.description)
            for item in examples
        ]
    )


def _discard_sandbox(session_id: str) -> None:
    """回退失败选用时产生的沙箱目录；不存在时静默返回。"""
    try:
        shutil.rmtree(workspace.workspace_dir(session_id), ignore_errors=True)
    except Exception:  # noqa: BLE001 - 回退失败不应掩盖原始错误
        pass


@router.post("/examples/apply", response_model=ExampleApplyResponse)
async def apply_example(
    request: Request,
    payload: ExampleApplyRequest,
    user: CurrentUser = Depends(current_user),
) -> ExampleApplyResponse:
    """选用一个示例：新建会话并把模板复制进沙箱，返回可直接预览的 session_id。"""
    user_id = user.session_user_id
    try:
        example = examples_service.find_example(payload.example_id)
    except examples_service.ExampleError as exc:
        raise HTTPException(status_code=500, detail=f"示例清单不可用：{exc}") from exc

    if example is None:
        raise HTTPException(status_code=404, detail=f"示例 {payload.example_id} 不存在")

    session = await create_session(request.app.state.session_service, user_id=user_id)
    try:
        examples_service.apply_to_session(
            session.id, example.id, request.app.state.settings
        )
    except examples_service.ExampleError as exc:
        # 复制失败不留残缺会话：回退沙箱并删除刚创建的空会话
        _discard_sandbox(session.id)
        try:
            await delete_session(
                request.app.state.session_service, user_id=user_id, session_id=session.id
            )
        except Exception:  # noqa: BLE001 - 会话删除失败不应掩盖原始错误
            pass
        raise HTTPException(status_code=500, detail=f"示例写入失败：{exc}") from exc

    return ExampleApplyResponse(
        session_id=session.id,
        example_id=example.id,
        message=f"已创建示例应用「{example.name}」，可直接预览，或继续对话修改它。",
    )