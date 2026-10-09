"""预置示例应用服务。

内置示例以静态模板随时间版本库发布在 `templates/examples/<示例 ID>/`，
清单登记在 `templates/examples/manifest.json`。这里负责读取清单、校验示例标识，
并把选定示例的模板目录复制进一个（新建的）会话沙箱（见 specs/example-apps/spec.md）。

示例是「已经写好、已经验证过」的成品：复制进沙箱后即可用既有的预览 / 版本 / 分享 / 下载
全链路，也能继续对话修改，完全不依赖实时模型生成。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.services import workspace

MANIFEST_NAME = "manifest.json"


class ExampleError(Exception):
    """示例清单缺失 / 格式非法，或请求的示例不可用。消息为可直接展示的中文说明。"""


@dataclass(frozen=True)
class Example:
    """一个内置示例应用的清单条目。"""

    id: str
    name: str
    description: str


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else workspace.TEMPLATES_ROOT


def load_examples(root: Path | None = None) -> list[Example]:
    """读取内置示例清单；文件缺失或格式非法时抛出 ExampleError。"""
    manifest = _root(root) / MANIFEST_NAME
    if not manifest.is_file():
        raise ExampleError(f"示例清单缺失：{manifest}")

    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExampleError(f"示例清单无法解析：{exc}") from exc

    items = raw.get("examples") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ExampleError("示例清单缺少 examples 数组。")

    examples: list[Example] = []
    for item in items:
        if not isinstance(item, dict) or "id" not in item or "name" not in item:
            raise ExampleError("示例清单项缺少 id 或 name 字段。")
        examples.append(
            Example(
                id=str(item["id"]),
                name=str(item["name"]),
                description=str(item.get("description", "")),
            )
        )
    return examples


def find_example(example_id: str, root: Path | None = None) -> Example | None:
    """按标识在清单中查找示例；不在清单内一律返回 None（不做路径拼接）。"""
    for example in load_examples(root):
        if example.id == example_id:
            return example
    return None


def template_dir(example_id: str, root: Path | None = None) -> Path:
    """定位示例的模板目录，并确认其位于模板根目录之内。"""
    base = _root(root).resolve()
    target = (base / example_id).resolve()
    if target != base and not target.is_relative_to(base):
        raise ExampleError(f"示例标识 {example_id!r} 非法。")
    return target


def apply_to_session(
    session_id: str,
    example_id: str,
    settings: Settings | None = None,
    root: Path | None = None,
) -> list[str]:
    """把示例模板复制进会话沙箱，返回写入的相对路径清单。

    先确认标识命中清单，再复制；标识未知或模板目录缺失都抛出 ExampleError，
    不创建半初始化内容（复制本身的清理由 workspace.init_from_template 保证）。
    """
    example = find_example(example_id, root)
    if example is None:
        raise ExampleError(f"示例 {example_id} 不存在。")
    try:
        return workspace.init_from_template(
            session_id, template_dir(example.id, root), settings
        )
    except workspace.WorkspaceError as exc:
        raise ExampleError(str(exc)) from exc