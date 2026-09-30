"""本地启动脚本。

设置 PYTHONUTF8=1（规避 Windows 下 LiteLLM 的编码问题），
校验配置后以 uvicorn 启动 app.main:app。

用法：py -3.12 run.py
"""

import os

os.environ.setdefault("PYTHONUTF8", "1")
# LiteLLM 会联网拉取模型价格表，网络受限时每次启动都要重试数秒，这里直接用内置表
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import sys  # noqa: E402

import uvicorn  # noqa: E402

from app.config import ConfigError, get_settings  # noqa: E402

if __name__ == "__main__":
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"[启动失败] {exc}", file=sys.stderr)
        print("请复制 .env.example 为 .env 并填写完整后重试。", file=sys.stderr)
        raise SystemExit(1) from None

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )