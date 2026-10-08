"""会话文件沙箱服务。

为每段会话提供互相隔离的沙箱目录（`data/workspace/<会话标识>/`），
对外提供路径安全校验、配额校验与文件写入/读取/列目录/删除/打包能力。

对应 specs/file-workspace/spec.md，设计依据见 design.md 决策 1、4、7、8：

- 沙箱根目录由会话标识唯一确定，位置与 sessions.db 同层，`data/` 已在 .gitignore 内。
- 路径安全基于 `resolve()` 后的真实路径判定：先显式拒绝绝对路径与含 `..` 的原始路径串，
  再确认解析结果仍位于沙箱之内，从而同时挡住 `..` 与符号链接两种逃逸。
- 失败一律抛出 WorkspaceError，消息为可直接交给模型的中文说明。

另有面向预览与版本的三组能力（见 specs/web-app-preview、specs/app-versions）：
`entry_path()` 定位入口 `index.html`，`read_asset()` 按相对路径取用单个静态资源，
`snapshot()` / `restore()` 把沙箱内容整目录复制为快照或由快照覆盖式重建。
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path

from app.config import PROJECT_ROOT, Settings, get_settings

# 沙箱根目录：与 SQLITE_DB_PATH 同层，data/ 已被 .gitignore 忽略
WORKSPACE_ROOT = PROJECT_ROOT / "data" / "workspace"

# 应用入口文件（见 specs/file-workspace/spec.md 的「应用入口文件的定位」）：
# 预览以它为起始页面，约定固定在沙箱根目录
ENTRY_FILE_NAME = "index.html"

# 空沙箱时给模型的说明（列目录要求「返回表示当前没有文件的结果，而不是报错」）
EMPTY_WORKSPACE_TEXT = "当前沙箱内没有任何文件。"

# 绝对路径：POSIX 的 `/x`、Windows 的 `\x` 与 `C:\x` 都算
_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")

# 预览按静态站点提供资源时按扩展名判定内容类型（未收录的一律当作二进制流）
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".bmp": "image/bmp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".xml": "application/xml",
    ".wasm": "application/wasm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
DEFAULT_CONTENT_TYPE = "application/octet-stream"


class WorkspaceError(Exception):
    """文件操作被拒绝或失败。消息为可直接展示给模型的中文说明。"""


def workspace_dir(session_id: str) -> Path:
    """该会话的沙箱根目录（已解析真实路径，不保证已存在）。

    会话标识同样不可信任（下载接口由使用者传入），因此与文件路径一样做越界校验。
    """
    root = WORKSPACE_ROOT.resolve()
    base = (root / str(session_id)).resolve()
    if base != root and not base.is_relative_to(root):
        raise WorkspaceError(f"会话标识 {session_id!r} 非法：不能指向沙箱根目录之外。")
    return base


def _safe_target_in(base: Path, relative_path: str) -> tuple[Path, Path, str]:
    """把相对路径解析为某个沙箱式目录内的真实路径，越界即拒绝。

    返回（基准目录、目标真实路径、规范化后的相对路径）。
    """
    raw = (relative_path or "").strip()
    if not raw:
        raise WorkspaceError("路径不能为空，请给出沙箱内的相对路径，例如 src/main.py。")
    if _ABSOLUTE_RE.match(raw):
        raise WorkspaceError(f"拒绝绝对路径 {raw!r}：只能使用相对于沙箱根目录的相对路径。")

    segments = [seg for seg in raw.replace("\\", "/").split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in segments):
        raise WorkspaceError(f"拒绝路径 {raw!r}：含上级目录片段，不能跳出会话沙箱。")
    if not segments:
        raise WorkspaceError(f"路径 {raw!r} 未指向任何文件，请给出具体文件路径。")

    base = Path(base).resolve()
    target = base.joinpath(*segments).resolve()
    if target != base and not target.is_relative_to(base):
        raise WorkspaceError(f"拒绝路径 {raw!r}：解析后的位置在会话沙箱之外。")
    return base, target, "/".join(segments)


def _safe_target(session_id: str, relative_path: str) -> tuple[Path, Path, str]:
    """把相对路径解析为会话沙箱内的真实路径，越界即拒绝。"""
    return _safe_target_in(workspace_dir(session_id), relative_path)


def _iter_files(base: Path) -> list[Path]:
    """沙箱内全部文件（不跟随符号链接进入目录）。"""
    if not base.is_dir():
        return []
    return sorted(path for path in base.rglob("*") if path.is_file())


def _relative(base: Path, path: Path) -> str:
    return path.relative_to(base).as_posix()


def _survey(base: Path) -> tuple[int, int]:
    """统计沙箱内文件数与总字节数。"""
    files = _iter_files(base)
    return len(files), sum(path.stat().st_size for path in files)


def list_files(session_id: str) -> list[str]:
    """沙箱内全部文件的相对路径清单（按路径排序）。"""
    base = workspace_dir(session_id)
    return [_relative(base, path) for path in _iter_files(base)]


def write_file(
    session_id: str,
    path: str,
    content: str,
    settings: Settings | None = None,
) -> tuple[str, int]:
    """写入文件，返回（规范化相对路径、字节数）。

    自动创建父目录，目标已存在时整体覆盖。任一项配额超限都在落盘前拒绝，
    因此失败时目标文件保持原有内容。
    """
    settings = settings or get_settings()
    base, target, relative = _safe_target(session_id, path)
    data = content.encode("utf-8")

    if len(data) > settings.workspace_max_file_bytes:
        raise WorkspaceError(
            f"写入被拒绝：内容为 {len(data)} 字节，超过单文件上限 "
            f"{settings.workspace_max_file_bytes} 字节。请拆分文件或减小单文件体积。"
        )
    if target.exists() and target.is_dir():
        raise WorkspaceError(f"写入被拒绝：{relative} 是一个目录，不能作为文件写入。")

    count, total = _survey(base)
    if target.exists():
        # 覆盖不增加文件数，也不重复计入原有体积
        new_count = count
        new_total = total - target.stat().st_size + len(data)
    else:
        new_count = count + 1
        new_total = total + len(data)

    if new_count > settings.workspace_max_files:
        raise WorkspaceError(
            f"写入被拒绝：该会话文件数将达到 {new_count} 个，超过上限 "
            f"{settings.workspace_max_files} 个。请先删除不再需要的文件。"
        )
    if new_total > settings.workspace_max_total_bytes:
        raise WorkspaceError(
            f"写入被拒绝：该会话沙箱总占用将达到 {new_total} 字节，超过上限 "
            f"{settings.workspace_max_total_bytes} 字节。请先删除不再需要的文件。"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative, len(data)


def read_file(session_id: str, path: str, settings: Settings | None = None) -> str:
    """读取文件文本内容；超过单文件上限时拒绝，避免模型基于残缺内容覆盖原文件。"""
    settings = settings or get_settings()
    _base, target, relative = _safe_target(session_id, path)

    if not target.exists():
        raise WorkspaceError(
            f"读取失败：{relative} 不存在。可先调用 list_files 查看沙箱内的文件。"
        )
    if target.is_dir():
        raise WorkspaceError(f"读取失败：{relative} 是一个目录，不是文件。")

    size = target.stat().st_size
    if size > settings.workspace_max_file_bytes:
        raise WorkspaceError(
            f"读取被拒绝：{relative} 为 {size} 字节，超过单次读取上限 "
            f"{settings.workspace_max_file_bytes} 字节。为避免基于残缺内容覆盖原文件，"
            f"请改为分块修改或重新生成该文件。"
        )
    return target.read_text(encoding="utf-8")


def delete_file(session_id: str, path: str) -> str:
    """删除沙箱内的单个文件，返回被删除的相对路径。"""
    _base, target, relative = _safe_target(session_id, path)

    if not target.exists():
        raise WorkspaceError(f"删除失败：{relative} 不存在。")
    if target.is_dir():
        raise WorkspaceError(
            f"删除被拒绝：{relative} 是一个目录。删除工具只作用于文件，"
            f"该目录及其内容保持不变。"
        )
    target.unlink()
    return relative


def zip_workspace(session_id: str) -> bytes | None:
    """把沙箱内全部文件打包为 zip 字节流，保留相对目录结构。

    沙箱为空时返回 None，由调用方给出明确提示，而不是返回空压缩包。
    """
    base = workspace_dir(session_id)
    files = _iter_files(base)
    if not files:
        return None

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=_relative(base, path))
    return buffer.getvalue()


# --- 应用入口与静态资源（供预览使用，见 specs/file-workspace/spec.md）---


def dir_entry_path(base: Path) -> Path | None:
    """定位某个沙箱式目录内的入口文件 `index.html`；不存在时返回 None。"""
    base = Path(base).resolve()
    if not base.is_dir():
        return None
    target = (base / ENTRY_FILE_NAME).resolve()
    if target != base and not target.is_relative_to(base):
        return None
    return target if target.is_file() else None


def entry_path(session_id: str) -> Path | None:
    """定位会话沙箱内的入口文件 `index.html`；不存在时返回 None。

    判定基于沙箱内的真实文件：符号链接指向沙箱之外的一律视为「无入口」，
    避免预览顺着链接读到沙箱外的内容。
    """
    return dir_entry_path(workspace_dir(session_id))


def guess_content_type(relative_path: str) -> str:
    """按扩展名给出内容类型，未收录的按二进制流处理。"""
    return CONTENT_TYPES.get(Path(relative_path).suffix.lower(), DEFAULT_CONTENT_TYPE)


def read_dir_asset(base: Path, relative_path: str) -> tuple[bytes, str]:
    """从某个沙箱式目录按相对路径取用单个文件，返回（内容字节、内容类型）。

    供预览（会话沙箱与分享快照）像静态站点一样提供入口页面及其相对引用的资源；
    沿用既有路径安全校验（拒绝绝对路径、`..` 与符号链接逃逸），并额外拒绝隐藏文件
    与隐藏目录——预览不需要暴露目录内的 `.env`、`.git` 一类内容。
    """
    _base, target, relative = _safe_target_in(base, relative_path)
    if any(segment.startswith(".") for segment in relative.split("/")):
        raise WorkspaceError(f"拒绝访问 {relative!r}：隐藏文件或目录不在预览范围内。")
    if not target.exists():
        raise WorkspaceError(f"资源不存在：{relative}。")
    if target.is_dir():
        raise WorkspaceError(f"资源不存在：{relative} 是一个目录，不能作为文件提供。")
    return target.read_bytes(), guess_content_type(relative)


def read_asset(session_id: str, relative_path: str) -> tuple[bytes, str]:
    """按会话沙箱内相对路径取用单个文件，返回（内容字节、内容类型）。"""
    return read_dir_asset(workspace_dir(session_id), relative_path)


# --- 快照与恢复（供版本服务使用，见 specs/file-workspace/spec.md）---


def snapshot(session_id: str, dest: Path) -> None:
    """把会话沙箱的全部内容整目录复制为一份独立快照。

    快照是独立副本，其内容不随沙箱后续改动而变化；只作用于本会话。
    """
    base = workspace_dir(session_id)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if base.is_dir():
        shutil.copytree(base, dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)


def restore(session_id: str, source: Path, keep: Path | None = None) -> None:
    """用某份快照覆盖式重建会话沙箱内容。

    keep 非空时，先把**当前**沙箱内容留存到该目录（使本次恢复可逆），
    再清空沙箱并从快照复制回来；操作只作用于本会话。
    """
    base = workspace_dir(session_id)
    if keep is not None:
        snapshot(session_id, keep)

    if base.is_dir():
        for child in base.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    source = Path(source)
    if source.is_dir():
        shutil.copytree(source, base, dirs_exist_ok=True)
    else:
        base.mkdir(parents=True, exist_ok=True)