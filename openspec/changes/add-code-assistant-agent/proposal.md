# Proposal

## Why

当前开发者需要代码辅助时，往往在通用聊天工具里散落地提问，缺少一个可复用的、专注代码场景的智能体服务：它既要能稳定地产出可读的多语言代码片段，又要把「对话」和「代码」以清晰的方式呈现出来。本变更用 Google ADK 搭建一个 Python agent 项目，接入 OpenAI 兼容的大模型服务（demo 阶段用免费的智谱 `glm-4.5-flash`），通过网页对话的形式为 Java / Python / C# / C++ 等常见语言提供代码生成、代码解释与重构优化辅助。

## What Changes

- 新增 Python 项目骨架，使用 Google Agent Development Kit（`google-adk` 2.x）作为 agent 框架。
- 新增模型接入层：以 OpenAI 兼容协议（base_url + api_key + model）通过 ADK 的 `LiteLlm` 包装器接入，全部配置来自环境变量，不硬编码密钥。
- 新增代码辅助 Agent：具备代码生成、代码解释、重构/优化三类核心能力，并通过系统指令约束输出语言为 Markdown 代码块（带语言标识）。
- 新增自定义 Web 对话前端：单页应用，支持多轮对话、流式输出（SSE）、代码块语法高亮与「复制代码」操作、目标语言切换。
- 新增 FastAPI 服务层：自定义 `/api/chat`（SSE 流式）、`/api/sessions` 等端点，直接驱动 ADK `Runner`，并托管静态前端。
- 新增会话管理：基于 ADK `SessionService` 保存多轮对话上下文，支持新建/切换会话。
- 新增工程化配置：依赖清单、`.env.example`、运行脚本、README 使用说明。
- **非目标（Non-goals）**：本版不做代码执行/沙箱运行、不做文件仓库级索引与 RAG、不做用户登录鉴权与多租户、不做报错调试排查能力（后续版本再评估）。

## Capabilities

### New Capabilities

- `web-chat`: 网页端与用户的多轮对话交互能力，包括流式增量展示、会话管理与代码片段的可视化呈现（语法高亮、语言标识、复制）。
- `code-assistant-agent`: 代码辅助智能体的应答能力，覆盖代码生成、代码解释、重构/优化三类任务，以及多语言输出与结构化代码块约束。
- `model-integration`: 模型接入与配置能力，包括 OpenAI 兼容端点配置、模型标识、连接失败的可诊断错误反馈。

### Modified Capabilities

<!-- 本项目为全新工程，暂无既有 capability 需要修改。 -->

## Impact

- **新增依赖**：`google-adk`（2.x，含 `extensions` extra 以启用 LiteLLM）、`litellm`、`fastapi`、`uvicorn`、`python-dotenv`、`sse-starlette` 等；前端使用 CDN 引入的轻量库（如 highlight.js），无需 Node 构建链路。
- **运行时要求**：Python ≥ 3.10（本机使用 3.12）；需要可访问所选 OpenAI 兼容服务端点的网络与凭据。
- **新增结构**：项目根目录新增 `app/`（agent、服务、接口、配置）、`prompts/`（提示词）、`web/`（静态前端）、`tests/`，以及 `openspec/`（规格与变更）、`.trae/`（OpenSpec 生成的工作流文件）。
- **风险**：ADK 2.x 相对 1.x 存在破坏性变更（图引擎执行、流式默认关闭、事件结构变化），需按 2.x 约定实现；非 Gemini 模型下 LiteLLM 的工具调用与流式支持存在差异，需在集成阶段验证。

**关于 TraeCode**：TraeCode CN 是订阅制 IDE 产品，官方不提供模型 API，无法作为本项目的后端模型。因此 `LLM_*` 配置指向任意 OpenAI 兼容服务，demo 阶段使用智谱 `glm-4.5-flash`（完全免费）。