# Tasks

## 1. 项目骨架与依赖

- [x] 1.1 按 design.md 的目录结构创建 `app/`、`app/agent/`、`app/services/`、`app/api/`、`prompts/`、`web/`、`tests/` 各级包目录与 `__init__.py`，验证方式是运行 `py -3.12 -c "import app"` 无导入错误
- [x] 1.2 创建 `requirements.txt`，锁定 `google-adk[extensions]`、`litellm`、`fastapi`、`uvicorn[standard]`、`python-dotenv`、`pydantic`、`pytest`，验证方式是在虚拟环境执行安装命令并成功结束
- [x] 1.3 创建 `.env.example`（含 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` / `APP_HOST` / `APP_PORT` / `SESSION_BACKEND` 占位项）与 `.gitignore`（忽略 `.env`、`.venv`、`__pycache__`、`data/`），验证方式是确认 `.env` 不会被 git 跟踪
- [x] 1.4 创建 `run.py` 启动脚本（设置 `PYTHONUTF8=1` 并以 uvicorn 启动 `app.main:app`），验证方式是执行后进程能监听配置端口
- [x] 1.5 在 `README.md` 中写明环境要求、安装、配置与启动步骤，验证方式是严格按 README 步骤在干净环境中可完成安装与启动

## 2. 配置层与模型接入

- [x] 2.1 实现 `app/config.py`：从环境变量与 `.env` 读取配置，校验必填项、`base_url` 以 `/v1` 结尾、端口为合法整数，并在缺失时抛出包含具体配置项名称的错误，验证方式是 `tests/test_config.py` 覆盖「完整配置」「缺 api_key」「base_url 无 /v1」三个用例并全部通过
- [x] 2.2 实现 `app/agent/model.py`：用 `LiteLlm(model="openai/<model>", api_base=..., api_key=...)` 构建模型对象，验证方式是单元测试断言模型标识与端点来自配置而非硬编码
- [x] 2.3 在 `app/main.py` 中落地配置加载与错误处理，验证方式是故意清空 `LLM_API_KEY` 启动时终端打印明确缺失项名称并以非零码退出

## 3. Agent 定义与提示词

- [x] 3.1 编写 `prompts/system.md`：约束三类任务（生成/解释/重构）、输出必须使用带语言标识的 Markdown 代码块、信息不足时先澄清、重构需说明改动原因，验证方式是逐条比对 `specs/code-assistant-agent/spec.md` 的每个 Requirement 都能在提示词中找到对应约束
- [x] 3.2 实现 `app/agent/prompt.py`：加载 `system.md` 并在未显式指定目标语言时追加语言推断与澄清规则，验证方式是单元测试断言加载内容包含关键约束句
- [x] 3.3 实现 `app/agent/root_agent.py`：定义 `LlmAgent`（名称、模型来自 `model.py`、指令来自 `prompt.py`）并导出 `root_agent`，验证方式是导入后断言 `root_agent.name` 与 `root_agent.model` 已被正确设置

## 4. 会话与事件流服务层

- [x] 4.1 实现 `app/services/runner.py`：按 `SESSION_BACKEND` 配置创建 `InMemorySessionService` 或 `SqliteSessionService`，并提供 `Runner` 单例的初始化与释放，验证方式是单元测试断言两种配置分别返回预期类型
- [x] 4.2 实现 `app/services/chat.py`：把 ADK `Event` 归一化为 `text` / `error` / `done` 三类帧（见 design.md 决策 4），验证方式是 `tests/test_chat_frames.py` 用构造的假事件覆盖「增量文本」「最终文本」「异常转 error」三类用例并全部通过
- [x] 4.3 在 `app/services/chat.py` 中接入 `RunConfig(streaming_mode=StreamingMode.SSE)` 驱动 `runner.run_async`，验证方式是以真实配置发起一次提问，控制台能观察到多个 `partial=true` 帧后紧跟一个 `done` 帧

## 5. HTTP 接口层

- [x] 5.1 实现 `app/schemas.py`：定义对话请求、会话响应与 SSE 帧的 pydantic 模型，验证方式是单元测试对帧模型做序列化后 JSON 字段与 design.md 决策 4 完全一致
- [x] 5.2 实现 `app/api/chat.py` 的 `POST /api/chat`：以 `text/event-stream` 流式返回帧，并设置 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`，验证方式是用命令行 HTTP 客户端请求该端点，能逐帧看到流式输出
- [x] 5.3 实现 `app/api/sessions.py` 的会话新建与查询端点，验证方式是调用新建接口返回的 `session_id` 可被后续对话请求复用
- [x] 5.4 在 `app/main.py` 中装配路由、`lifespan` 生命周期与 `StaticFiles` 静态托管，验证方式是访问 `/` 返回 `web/index.html` 且 `/api/chat` 可用

## 6. 前端对话页面

- [x] 6.1 实现 `web/index.html` 与 `web/styles.css`：消息列表、输入框、发送按钮、目标语言下拉（Java/Python/C#/C++/HTML/JavaScript/自动）、新建会话按钮，验证方式是浏览器中元素齐全且布局在窄屏下不溢出
- [x] 6.2 实现 `web/app.js` 的 SSE 消费逻辑：按帧类型增量追加文本、异常时保留已收内容并提示错误、结束时收尾，验证方式是在浏览器中提问后观察文本逐步出现，并断开服务端验证错误提示出现
- [x] 6.3 在 `web/app.js` 中实现 Markdown 与代码块渲染（marked + highlight.js + DOMPurify）：渲染语言徽标与复制按钮，验证方式是提问生成 Java 与 Python 代码后，代码高亮与语言标识正确、复制按钮可用，且未标注语言的代码块也正常渲染
- [x] 6.4 实现新建会话与目标语言选择的联动请求逻辑，验证方式是新建会话后消息列表清空，选择 C++ 后生成的代码为 C++

## 7. 集成验证

- [x] 7.1 端到端验收：按 `specs/code-assistant-agent/spec.md` 的三类任务各执行一次真实提问（其中一次选择 HTML 或 JavaScript 目标语言），确认代码语言标识、说明文字与可复制性均符合要求
- [x] 7.2 回归 `specs/web-chat/spec.md` 的全部 Scenario（含流式中断、未标注语言代码块、同一会话追问），逐条记录通过情况
- [x] 7.3 验证 `specs/model-integration/spec.md` 的错误场景：模拟端点不可达与凭据无效，确认错误信息能区分两类原因；再切换 `LLM_MODEL` 确认无需改代码即生效
- [x] 7.4 运行 `py -3.12 -m pytest` 确认全部单元测试通过，并将运行结果与已知限制写入 `README.md`