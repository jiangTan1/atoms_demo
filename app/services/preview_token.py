"""预览票据的签发与校验。

预览 iframe 使用不含 `allow-same-origin` 的沙箱（见 design.md 决策 3），其中的文档处在
不透明源。它自己发起的样式与脚本请求会被浏览器视为**跨站**，`SameSite=Lax` 的登录态
Cookie 不随之发送，服务端于是以 401 拒绝（响应体是 JSON）；而这类跨源响应在 script /
stylesheet 目的下又会命中 Chrome 的 ORB（Opaque Response Blocking），被直接拦掉。
结果是入口页面能返回、样式与脚本却全部加载失败：预览里「看得见界面、点不动」。

因此预览改用**路径内票据**：入口地址形如 `/preview/<会话标识>/<票据>/`。
页面里的相对路径天然带上同一段前缀，子资源无需 Cookie 即可取用，也就不再出现 401 与 ORB。

票据是无状态签名：`有效期时间戳 + HMAC-SHA256(密钥, 会话标识:有效期)`。
密钥在进程启动时随机生成，因此票据不可伪造、不能挪用到别的会话，且只在本进程生命周期内有效
（部署约定 uvicorn `--workers 1`，见 docs/project-overview.md）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

# 签名密钥：进程启动时随机生成，随进程结束失效。
# 失效只会让前端重新换取一次票据，不影响正确性。
_SECRET = secrets.token_bytes(32)

# 票据有效期：覆盖一次预览交互即可，过期后前端重新换取新票据。
DEFAULT_TTL_SECONDS = 3600


def _digest(session_id: str, expires_at: int) -> bytes:
    message = f"{session_id}:{expires_at}".encode("utf-8")
    return hmac.new(_SECRET, message, hashlib.sha256).digest()


def issue(session_id: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> tuple[str, int]:
    """签发该会话的预览票据，返回（票据、有效期秒数）。"""
    expires_at = int(time.time()) + ttl_seconds
    signature = base64.urlsafe_b64encode(_digest(session_id, expires_at)).decode("ascii")
    return f"{expires_at}.{signature.rstrip('=')}", ttl_seconds


def verify(session_id: str, token: str) -> bool:
    """校验票据由本进程签发、未过期，且绑定的正是该会话。"""
    expires_raw, _, signature = (token or "").partition(".")
    if not signature:
        return False
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return False
    if expires_at < int(time.time()):
        return False

    # base64 的填充位被签发时去掉，这里按需补回；非法字符会抛 ValueError（含 binascii.Error）
    try:
        provided = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    except ValueError:
        return False
    return hmac.compare_digest(_digest(session_id, expires_at), provided)