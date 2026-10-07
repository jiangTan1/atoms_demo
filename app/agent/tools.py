"""Agent 沙箱文件工具。

以普通函数定义四个文件工具（write_file / read_file / list_files / delete_file），
交给 ADK 自动包装为 FunctionTool：docstring 即工具描述，签名中的 `tool_context`
由框架按类型注解，据此取出当前会话标识并推导该会话的沙箱目录（见 design.md 决策 2、3）。

失败情形一律以文本结果返回而不抛异常：ADK 会把返回文本作为 function_response
回灌给模型，模型据此纠正重试或向使用者说明，本次对话不中断（见 design.md 决策 6）。
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from app.services import workspace

# 成功与失败结果的统一措辞，便于模型区分「已生效」与「未生效」
_WRITE_OK = "已写入 {path}（{size} 字节）。"
_DELETE_OK = "已删除 {path}。"
_LIST_EMPTY = workspace.EMPTY_WORKSPACE_TEXT


def _failure(exc: Exception) -> str:
    return f"文件操作未生效：{exc}"


def write_file(path: str, content: str, tool_context: ToolContext) -> str:
    """把文本内容写入当前会话沙箱内的文件。

    仅当需要把生成结果真实落盘时调用（例如使用者要求生成一个含多个文件的项目）；
    只是提问、解释代码或排查缺陷时不要调用。

    父目录会自动创建，目标文件已存在时整体覆盖；同一文件请在最终内容确定后一次写入，
    不要反复覆盖。单文件字节数、文件数与沙箱总体积受服务端配额限制。

    Args:
        path: 相对于沙箱根目录的相对路径，例如 "src/main.py"。禁止绝对路径与 `..`。
        content: 要写入的完整文本内容。
    """
    try:
        relative, size = workspace.write_file(tool_context.session.id, path, content)
    except (workspace.WorkspaceError, OSError) as exc:
        return _failure(exc)
    return _WRITE_OK.format(path=relative, size=size)


def read_file(path: str, tool_context: ToolContext) -> str:
    """读取当前会话沙箱内某个文件的内容。

    修改已生成的文件前，先用本工具读取其现有内容，再基于该内容写入完整的新版本，
    不要凭记忆重新生成整个项目。

    Args:
        path: 相对于沙箱根目录的相对路径，例如 "src/main.py"。
    """
    try:
        return workspace.read_file(tool_context.session.id, path)
    except (workspace.WorkspaceError, OSError) as exc:
        return _failure(exc)


def list_files(tool_context: ToolContext) -> str:
    """列出当前会话沙箱内的全部文件（相对路径清单）。

    在修改或继续生成项目前，可先用本工具确认沙箱内已有的文件，避免重复创建或覆盖错文件。
    """
    try:
        paths = workspace.list_files(tool_context.session.id)
    except (workspace.WorkspaceError, OSError) as exc:
        return _failure(exc)
    if not paths:
        return _LIST_EMPTY
    return "当前沙箱内的文件：\n" + "\n".join(paths)


def delete_file(path: str, tool_context: ToolContext) -> str:
    """删除当前会话沙箱内的单个文件，用于纠正错误的产物。

    只作用于文件，不能删除目录；同一轮对话中若某文件已写错，可先删除再重新写入。

    Args:
        path: 相对于沙箱根目录的相对路径，例如 "src/old_main.py"。
    """
    try:
        relative = workspace.delete_file(tool_context.session.id, path)
    except (workspace.WorkspaceError, OSError) as exc:
        return _failure(exc)
    return _DELETE_OK.format(path=relative)


# 装配到 LlmAgent 的工具集：仅沙箱文件读写，不含执行命令或访问网络的能力
FILE_TOOLS = [write_file, read_file, list_files, delete_file]