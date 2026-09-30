# Design

## Context

参见 proposal.md 的 Why。驱动本设计的关键事实来自对 ADK 2.10.0 的核实：

- `google-adk` 2.x 要求 Python ≥ 3.10（本机用 3.12）。LiteLLM 支持被拆到 extra 中，需 `pip install "google-adk[extensions]"`，且 LiteLLM 本体要求 `litellm>=1.84`。
- 接入非 Gemini 的 OpenAI 兼容端点使用 `google.adk.models.lite_llm.LiteLlm`，模型串必须以 `openai/` 为前缀（`LiteLlm(model="openai/<model>", api_base=..., api_key=...)`），`api_base` 需带 `/v1` 后缀。
- ADK 2.x 默认**不流式**：网页场景必须显式传 `RunConfig(streaming_mode=StreamingMode.SSE)` 给 `runner.run_async(...)`。
- 2.x 执行引擎改为图引擎：直接覆写 `_run_async_impl()` 会被静默忽略，需要干预时改用回调；禁止直接向 session 追加事件，必须 `yield` 事件。
- `get_fast_api_app(...)` 可快速起一个带内置 Dev UI 的服务，但它按 `agents_dir` 约定发现 agent，且未提供自定义静态前端目录的参数。

另外，ADK 的 `Runner.run_async` 只能异步消费，天然适配 SSE；而前端的代码高亮、语言标识、复制按钮属于纯展示层，不需要构建工具链。

## Goals / Non-Goals

**Goals:**

- 用最小依赖搭出可运行的分层骨架：前端 → HTTP/SSE 接口 → 会话与 Runner 服务 → Agent → 模型接入。
- 让「模型接入配置」「Agent 行为」「HTTP 接口」「前端展示」四层彼此解耦，任何一层可独立替换或测试。
- 执行链路端到端可见：一次提问能明确看到请求进入、Agent 事件流、SSE 分帧、前端增量渲染的完整过程。
- 未来可平滑切换到 ADK 内置 UI 或其它 OpenAI 兼容模型。

**Non-Goals:**

- 不做代码执行沙箱、文件系统读写工具、仓库级索引与 RAG。
- 不做用户体系、鉴权、多租户隔离与限流。
- 不引入前端构建链路（不使用 React/Vite/TypeScript 编译）。
- 不引入数据库迁移框架；会话持久化先用 ADK 自带实现。

## Decisions

### 1. 框架与模型接入：`google-adk` 2.x + `LiteLlm`

`Agent` 的 `model` 传入 `LiteLlm(model="openai/<LLM_MODEL>", api_base=<LLM_BASE_URL>, api_key=<LLM_API_KEY>)`。demo 阶段先用智谱 `glm-4.5-flash`（完全免费，`https://open.bigmodel.cn/api/paas/v4`）。

- **理由**：LiteLlm 是 ADK 官方提供、用于对接 OpenAI 兼容端点的唯一路径；把端点差异隔离在这一个对象里，Agent 与业务代码不感知具体供应商。
- **备选**：直接用 Gemini 原生模型（被排除，需求指定 OpenAI 兼容端点）；自己写 `BaseLlm` 子类（被排除，重复造轮子且要自己处理流式与工具调用）。

注：TraeCode CN 是订阅制 IDE 产品，不对外提供模型 API，无法作为本项目的后端模型，因此 `LLM_*` 指向的是任意 OpenAI 兼容服务。

### 2. 自定义 FastAPI + SSE，而非 `get_fast_api_app` + 内置 UI

自建 `FastAPI` 应用，用 `/api/chat` 以 `text/event-stream` 返回增量事件，用 `StaticFiles` 挂载 `web/`。通过 `lifespan` 管理 `Runner` 与 `SessionService` 的单例创建与释放。

- **理由**：需求要求自定义的前端展示（代码高亮、语言选择、会话切换），`get_fast_api_app` 的端点和前端都由框架决定，定制成本高；自建 SSE 端点还能统一错误协议，满足「流式中断要有可识别错误提示」的要求。
- **备选**：`get_fast_api_app(agents_dir=..., web=True)` 直接用内置 Angular Dev UI（被排除：展示层无法定制）；`adk web` 命令（被排除：仅适合本地调试）。

### 3. 会话状态：默认 `InMemorySessionService`，预留可切换

`SessionService` 通过工厂函数按配置返回 `InMemorySessionService` 或 `SqliteSessionService`（`sqlite:///./data/sessions.db`），默认内存态。

- **理由**：InMemory 满足单机演示与开发验证；ADK 已内置 SQLite 实现，切换成本仅为改一行配置，无需自研持久层。
- **备选**：`DatabaseSessionService` 接 PostgreSQL（被排除：首版引入数据库运维成本不合理）。

### 4. 流式事件 → SSE 的协议

`Runner.run_async` 产出的每个 `Event` 由服务层归一化为 JSON 帧再发出，事件类型固定为：

- `{"type": "text", "data": "<增量文本>", "partial": true|false}`
- `{"type": "error", "data": {"code": "...", "message": "..."}}`
- `{"type": "done", "data": {"session_id": "...", "message_id": "..."}}`

只有 `event.content.parts` 中的文本会被作为 `text` 帧下发；`partial=True` 的增量直接推送，最终事件补一个 `partial=false` 的完整帧，避免前端在丢帧时内容不完整。

- **理由**：固定帧类型让前端渲染逻辑简单、可测；显式 `error` / `done` 帧满足错误可诊断要求。
- **备选**：直接透传 ADK 原始 `Event` 结构（被排除：前端要理解 ADK 内部结构，耦合过重）。

### 5. 前端：单页静态页面 + CDN 轻量库

`web/index.html` + 原生 JS，`marked`（Markdown 渲染）与 `highlight.js`（代码高亮）+ `DOMPurify`（渲染净化）通过 CDN 引入，代码块渲染后追加语言徽标与复制按钮。

- **理由**：零构建链路、零 npm 依赖，符合「轻量前端」取向，评审和改动都直观。
- **备选**：React/Vite（被排除：为一个对话页引入构建链路不划算）。

### 6. 目录结构（本变更交付的骨架）

```text
demo/
├─ app/                          # 后端应用包（Python）
│  ├─ main.py                    # FastAPI 装配、静态托管、uvicorn 入口
│  ├─ config.py                  # 环境变量读取 + 必填校验（配置层）
│  ├─ schemas.py                 # 请求/响应与 SSE 帧的 pydantic 模型
│  ├─ agent/
│  │  ├─ root_agent.py           # ADK Agent 定义，导出 root_agent
│  │  ├─ model.py                # OpenAI 兼容端点的 LiteLlm 构建（模型接入层）
│  │  └─ prompt.py               # 系统提示词加载与语言约束拼装
│  ├─ services/
│  │  ├─ runner.py               # Runner / SessionService 生命周期管理
│  │  └─ chat.py                 # Event → SSE 帧的转换与错误归一化
│  └─ api/
│     ├─ chat.py                 # POST /api/chat（SSE 流式对话）
│     └─ sessions.py             # 会话新建/查询
├─ prompts/
│  └─ system.md                  # 系统提示词（含代码块与语言约束）
├─ web/                          # 静态前端
│  ├─ index.html
│  ├─ styles.css
│  └─ app.js
├─ tests/
│  ├─ test_config.py
│  └─ test_chat_frames.py
├─ .env.example                  # 模型配置样例（不含真实密钥）
├─ .gitignore
├─ requirements.txt
├─ run.py                        # 本地启动脚本
└─ README.md
```

- **理由**：按「配置 / 模型接入 / Agent / 服务 / 接口 / 展示」切分，每层单一职责，便于逐层评审；`prompts/` 与 `web/` 放在包外，便于非 Python 使用者直接修改。

## Risks / Trade-offs

- [ADK 2.x 与 1.x 不兼容，网上示例多为 1.x 写法] → 以 2.10.0 实测为准，先做一次最小连通性验证（模型连通 + 流式帧），再铺开实现。
- [LiteLLM 下非 Gemini 模型的工具调用/流式支持程度不一] → 首版 Agent 不依赖工具调用即可完成三类任务；若后续加工具，单独做一次兼容性验证。
- [`api_base` 缺少 `/v1` 或缺少 API key 会导致 404/鉴权失败，报错信息晦涩] → 在配置层做格式校验（如 base_url 以 `/v1` 结尾），并在服务层区分网络不可达与鉴权失败。
- [SSE 经过反向代理可能被缓冲，导致「不流式」] → 响应头显式设置 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`。
- [Windows 下 LiteLLM 的编码问题] → 启动脚本设置 `PYTHONUTF8=1`。
- [前端用 CDN 引入库，离线环境不可用] → README 说明；如需离线，可将三个库文件下载到 `web/vendor/` 并改为本地引用。

## Migration Plan

全新项目，无历史数据迁移。上线路径：配置 `.env` → 安装依赖 → `python run.py` → 浏览器访问 `http://127.0.0.1:8000`。回滚即停止服务；因默认使用内存会话，无残留状态。

## Open Questions

- （已解决）模型端点的 `base_url`、模型标识与 API Key：demo 阶段使用智谱 `glm-4.5-flash`（完全免费），正式环境替换为付费的 OpenAI 兼容服务，仅需改 `.env`。
- 会话是否需要跨重启持久化：默认内存即可满足首版，如需要改为 SQLite 只需切换一个配置项，不改动接口。