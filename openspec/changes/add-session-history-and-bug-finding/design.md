# Design

## Context

参见 proposal.md 的 Why。本设计基于对本项目现状与 ADK 2.10.0 的核实：

- 现有会话后端由 `SESSION_BACKEND` 选择，`app/services/runner.py` 的 `create_session_service()` 已支持 `InMemorySessionService` 与 `SqliteSessionService`，切换成本仅为一个配置项。
- `SqliteSessionService(db_path=...)` 接受文件路径；`app/services/runner.py` 中已固定 `SQLITE_DB_PATH = <项目根>/data/sessions.db`。
- `BaseSessionService.list_sessions(app_name=..., user_id=...)` 返回的 `ListSessionsResponse.sessions` **不含事件**（`events` 计数为 0），只有 `id` / `app_name` / `user_id` / `state` / `last_update_time`（float epoch）。
- 实测一轮对话在会话中落盘 **2 条事件**：`author='user'`（用户消息原文）与 `author='code_assistant'`（`partial=False` 的完整文本）；无 partial 中间态被持久化。
- `POST /api/chat` 在未传 `session_id` 时自动新建会话，并在 `done` 帧中回传 `session_id`，前端已据此更新本地变量。
- 现有 `GET /api/sessions/{session_id}` 仅返回 `{session_id, user_id}`，不含消息内容。

## Goals / Non-Goals

**Goals:**

- 对话内容可持久化，刷新页面与服务重启后都能找回。
- 历史会话可列表、可切换，切换后上下文连续。
- 缺陷排查作为第四类任务生效，且不增加界面复杂度。
- 保持既有 SSE 帧协议与接口调用方式不变，前端与后端改动互不破坏。

**Non-Goals:**

- 不做静态分析器、编译级检查或代码执行；缺陷识别完全依赖提示词与模型判断。
- 不做会话重命名、删除、搜索、导出。
- 不做登录鉴权与多用户隔离，仍固定使用 `web-user`。
- 不引入前端构建链路或新的第三方依赖。

## Decisions

### 1. 会话持久化：改用 ADK 内置 `SqliteSessionService`，并将其设为默认

`SESSION_BACKEND` 默认值由 `memory` 改为 `sqlite`；`config.py` 的默认取值、`.env`、`.env.example` 三处同步。

- **理由**：ADK 已内置 SQLite 实现，只需改一个配置项即可满足「刷新与重启后仍有历史」，无需自研持久层。
- **备选**：自研 JSON/消息表（被排除：需自行处理事件结构与并发）；`DatabaseSessionService` 接 PostgreSQL（被排除：demo 引入数据库运维成本不合理）。

### 2. 历史消息从 ADK 会话事件推导，不另建消息表

新增还原函数（放在 `app/services/chat.py`），把会话事件列表映射为 `{"role": "user"|"assistant", "text": ...}`：

- `author == 'user'` → `role=user`，文本取事件内容原文。
- 其他作者 → `role=assistant`。
- 跳过 `partial=True`、空文本、以及只含 `error_code` 的事件。

- **理由**：ADK 已是唯一事实来源，重复建表会带来双写不一致风险；实测事件结构简单（一轮仅 2 条），还原规则稳定可测。
- **备选**：在 `data/` 下自建消息表（被排除：需要额外同步逻辑与迁移）。

### 3. 会话列表为「逐会话读取 + 限量倒序」

列表端点内部流程：`list_sessions` 取会话集合 → 按 `last_update_time` 倒序截取最近 N 个（N=50）→ 对每个会话 `get_session` 推导标题与消息数 → 返回。

- 标题：该会话首条用户消息的前若干字符（截断并加省略号）；无用户消息时标记为空会话。
- **理由**：`list_sessions` 不含事件，标题与消息数只能逐会话读取（N+1 次查询）；demo 规模下可接受，用限量与倒序把开销封顶。
- **备选**：只返回 id 与时间（被排除：列表不可辨识，体验差）；把标题缓存进 `session.state`（被排除：需在写入路径改造，收益不足）。

### 4. 新增端点与既有端点的关系

- `GET /api/sessions`：历史会话列表（新增）。
- `GET /api/sessions/{session_id}/messages`：历史消息（新增）。
- `GET /api/sessions/{session_id}`：保持原样（存在性查询），响应结构不变。

- **理由**：路径互不冲突（FastAPI 先精确匹配静态段，再匹配带参路由），列表与详情职责分离，前端可分别按需请求。
- **备选**：把消息塞进 `GET /api/sessions/{session_id}` 的响应（被排除：破坏既有响应契约）。

### 5. 前端以 localStorage 记住当前会话

- 键名：`code-assistant.session_id`。
- 页面加载顺序：读键值 → 拉历史消息渲染 → 拉历史会话列表渲染面板；拉取失败或返回 404 时清除键值并进入新会话状态。
- 历史会话面板放在顶栏，点击条目即切换会话并重渲染消息区。

- **理由**：localStorage 零依赖、同源可用，满足「刷新后自动回到上次会话」；服务端仍是权威，客户端失效时可回退。
- **备选**：服务端记住「当前会话」（被排除：单用户 demo 下反而引入额外状态）。

### 6. 缺陷排查：靠提示词识别，不新增界面控件

在 `prompts/system.md` 中新增「任务四：缺陷排查与优化点识别」，并把开头「只处理三类任务」更新为四类。输出结构约束为：问题清单（严重程度 / 位置 / 触发条件 / 后果）→ 修复后的完整代码 → 改动说明；无实质问题时须如实说明并最多给出少量可选优化点。

- **理由**：使用者的问法本身就是意图信号（贴代码 + "有什么问题"），加模式开关只会增加认知负担；提示词约束与既有三类任务风格一致，实现成本最低。
- **备选**：界面加「排查模式」开关（被排除：与「不增加界面复杂度」的取向冲突）；用工具做静态检查（被排除：超出本版范围）。

## Risks / Trade-offs

- [列表接口的 N+1 查询在大会话量下变慢] → 倒序取最近 50 个并只读元数据；若后续会话量增大，再考虑缓存标题。
- [`localStorage` 记录的会话已在服务端失效（清库或换机器）] → 前端捕获 404 后清除记录并进入新会话状态，仅给轻量提示。
- [从内存后端切到 SQLite 后旧会话不可见] → 属预期行为，在 README 说明；demo 无迁移负担。
- [模型可能对无缺陷代码硬凑问题] → 提示词显式要求「无问题须如实说明，不得凑数」，并在验收中专门验证该场景。
- [历史消息中的助手内容为 Markdown，直接渲染可能与当时流式结果存在细微差异] → 复用现有渲染管线（marked + highlight.js + DOMPurify），保证展示一致。

## Migration Plan

1. 改 `SESSION_BACKEND` 默认为 `sqlite`，同步 `config.py`、`.env`、`.env.example`。
2. 后端加还原函数与两个新端点，跑单元测试。
3. 前端接入 localStorage 与历史面板。
4. 提示词更新第四类任务。
5. 端到端验收：多轮对话 → 刷新页面确认历史仍在 → 重启服务确认会话仍可列出 → 提交有缺陷代码确认排查输出结构。

回滚：把 `SESSION_BACKEND` 改回 `memory` 即恢复无持久化形态；新端点为只读，删除后不影响既有对话链路。

## Open Questions

- （已解决）历史会话列表是否需要分页：首版按最近更新时间倒序返回最近 50 条，暂不做分页。
- 是否为会话提供重命名与删除：本版不做，待使用者反馈后再评估。