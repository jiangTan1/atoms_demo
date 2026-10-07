# Design

## Context

动机见 proposal.md 的 Why。本设计基于对项目现状与 ADK 2.10.0 源码的核实：

- `root_agent` 是**模块级单例**（`app/agent/root_agent.py`），`LlmAgent` 的 `tools` 只能在构建时确定，无法逐请求变化。
- 现有流式处理：`app/services/chat.py` 的 `extract_text()` 只取有 `.text` 且非 `thought` 的部件；`FrameBuilder.consume()` 在 `partial=True` 时按增量下发并累积，在 `partial=False` 时用累积文本补一个完整帧。`stream_frames()` 在 `async for` 结束后产出 `done` 帧。
- 会话标识在接口层已可用（`app/api/chat.py` 持有 `session` 与 `session_id`），历史会话查询走 `app/services/runner.py` 的 `get_session()`。
- 前端已有 `saveAsFile()`（Blob + `<a download>`）这一下载实现，可复用。
- 配置文件已固定落在 `data/` 下（`SQLITE_DB_PATH = PROJECT_ROOT / "data" / "sessions.db"`），且 `data/` 已被 `.gitignore` 忽略。

ADK 2.10.0 的关键事实（含证据位置，均在 `.venv/Lib/site-packages/google/adk/`）：

1. `agents/llm_agent.py:162-214` 的 `_convert_tool_union_to_tools` 会把普通 `callable` 自动包装为 `FunctionTool`，因此可以把 Python 函数直接放进 `tools=[...]`。
2. `tools/function_tool.py:95-126` 与 `:268-301`：工具描述取自函数 docstring，参数类型来自注解；签名中出现上下文参数（默认名 `tool_context`）时由框架注入。
3. `tools/tool_context.py:21-28`：`ToolContext` 是 `Context` 的别名；`agents/readonly_context.py:39-64` 与 `agents/context.py:301-305` 表明可经它访问 `session`（含 `session.id`）。
4. `agents/_streaming_mode.py:51-92`：SSE 模式下存在「部分文本事件」「部分工具调用事件」与「聚合事件（`partial=False`）」三类；模型发起工具调用的事件里是 `function_call` 部件（无 `.text`），工具结果回灌的事件里是 `function_response`；**一轮 `run_async` 可以出现「文本 → 工具调用 → 更多文本」的交替**。
5. `events/event.py:283-305`：`is_final_response()` 的实现是「无 function call、无 function response、且 `partial=False`」。
6. `tools/environment/_environment_toolset.py:45-95`：ADK 自带 `ExecuteTool`、`ReadFileTool`、`EditFileTool`、`WriteFileTool`，它们的操作委托给一个 `environment` 实例；`environment/_local_environment.py` 的 `working_dir` 在环境构造时固定。
7. 工具执行失败时由工具自身返回 `{'status': 'error', 'error': ...}` 并作为 `function_response` 回灌给模型（`tools/environment/_write_file_tool.py:38-86`），**不经由 `Event.error_code`**。

## Goals / Non-Goals

**Goals:**

- 生成的文件真实落盘到按会话隔离的沙箱，会话之间互不影响。
- 沙箱边界可证明：任何输入路径都无法读写沙箱之外的内容。
- 沙箱占用有上界，一次对话不可能写爆磁盘。
- 挂上工具后既有流式打字机体验与帧协议不退化。
- 前端一键取走整套文件且保留目录结构。

**Non-Goals:**

- 不给智能体任何执行命令、安装依赖或访问网络的能力。
- 不做文件内容校验（不判断模型写的代码是否正确、是否可运行）。
- 不做沙箱清理与生命周期回收（历史会话当前不支持删除）。
- 不做多用户与鉴权隔离，沿用全站既有的「无鉴权」现状。
- 不做文件清单界面、单文件下载与在线预览。

## Decisions

### 1. 沙箱根目录固定为 `data/workspace/<session_id>/`

- **理由**：一个会话即一个项目，与既有「会话落盘 sqlite」的模型一致；会话之间天然隔离；历史会话的文件随会话保留，符合使用者直觉。位置与 `SQLITE_DB_PATH` 同层，`data/` 已被 `.gitignore` 覆盖，无需改忽略规则。
- **备选**：所有会话共享一个工作区（被排除：多会话同名文件互相覆盖，且"一个会话一个项目"的语义消失）；把根目录做成可配置项（本版不做，记入 Open Questions）。

### 2. 不复用 ADK 自带的 `tools/environment` 工具族，自写函数工具

- **理由**（依据 Context 第 6 条）：`EnvironmentToolset` 的沙箱根目录由 `environment` 实例在**构造时**固定，而本方案要求根目录随每个请求的 `session_id` 变化；该工具族还缺少「列目录」与「删除」，却带了一个本变更明确不要的 `ExecuteTool`。自写四个函数工具用 `tool_context` 取会话 ID，逻辑直白且边界可控。
- **备选**：为每个会话动态构造 `LocalEnvironment` 并组成动态 Toolset（被排除：Agent 是模块级单例，逐请求重建工具集的复杂度远超收益）；只挂 `WriteFileTool`（被排除：根目录无法按会话变化，且缺少列目录/删除，无法支撑"增量修改"）。

### 3. 会话 ID 经 `tool_context` 注入，不依赖闭包或 session.state

- **理由**（依据 Context 第 1-3 条）：ADK 会自动把 `ToolContext` 注入同名参数，`tool_context.session.id` 即当前会话标识。工具函数因此是纯函数式的：由入参与上下文决定行为，不需要在构建期绑定会话，也不需要往 `session.state` 写路径。
- **备选**：把沙箱路径写进 `session.state` 并在 Runner 回调里维护（被排除：需要在写入路径上改造状态增量，收益不足）；从 `invocation_id` 反推（被排除：语义不同，`invocation_id` 每次调用都会变）。

### 4. 路径校验基于 `resolve()` 后的真实路径

- **做法**：先显式拒绝绝对路径与含 `..` 的原始路径串（给出明确的中文失败说明）；再拼出「沙箱根 / 相对路径」，调用 `Path.resolve()` 解析 `..` 与符号链接，校验结果仍位于 `resolve()` 后的沙箱根之内，否则拒绝。
- **理由**：`resolve()` 一次覆盖上级目录片段与符号链接两种逃逸，而校验必须基于**真实路径**比较，否则 `沙箱/../x` 这类写法能绕过任何字符串前缀检查。
- **备选**：只做字符串前缀匹配（被排除：符号链接与 `..` 均可绕过）；用正则过滤危险字符（被排除：Windows 与 POSIX 的路径语义不同，正则会漏）。

### 5. 完整帧改为「事件流结束后」统一产出（本变更最关键的既有逻辑改造）

- **问题**（依据 Context 第 4、5 条）：挂上工具后，一轮对话会出现「文本 → 工具调用 → 更多文本」的交替，`partial=False` 不再等价于"本轮最终回复"；而 `is_final_response()` 按本版本的实现同样会把中间那个纯文本的聚合事件判为最终回复，因此也不能用来分辨轮次结束。现状下 `FrameBuilder` 会在一轮里产出多个"完整帧"，前端据其覆盖整段内容，会出现文本重复或跳变。
- **做法**：`partial=True` 且有文本的事件照常按增量下发并累积；**把完整帧的产出从事件分支移出**，改在 `stream_frames()` 的 `async for` 结束之后，用累积文本产出一次 `partial=False` 帧。
- **理由**：判定依据从「某个事件标记」变为「流已结束」，不依赖 ADK 对 `partial` / `is_final_response` / 未来可能出现的 `turn_complete` 的语义约定，契约更稳：**流结束即完整帧**，与既有「最终帧提供完整内容兜底」的语义完全一致。
- **连带影响**：`message_id` 仍取最后一次带 `id` 的事件，因此 `done` 帧内容不变；完整帧的到达时刻比原来晚一次循环收尾的时间量，对使用者不可感知。
- **备选**：改用 `event.is_final_response()` 判定（被排除：如上，中间聚合事件同样满足条件，仍会误判）；为工具轮次单独计数并只在末轮产出（被排除：需要猜测轮次边界，脆弱）。

### 6. 工具失败以文本回灌，不升级为 SSE 错误帧

- **理由**（依据 Context 第 7 条）：工具失败由 ADK 作为带 error 字段的 `function_response` 回灌给模型，模型看到失败说明后可以自行纠正重试或向使用者解释。这正好满足「工具失败不中断对话」的要求，因此 `FrameBuilder` 不需要为工具错误增加分支。
- **连带结论**：`function_call` / `function_response` 部件没有 `.text`，会被 `extract_text()` 自然跳过；`events_to_messages()` 还原历史时同理（文本为空即跳过），因此工具调用**不会**在历史里留下多余消息，也不会干扰既有的澄清轮次计数。
- **备选**：把工具失败提升为 `error` 帧（被排除：会让可自愈的参数错误变成使用者可见的连接错误，体验更差）。

### 7. 配额上限走配置层，键为可选带默认值

新增三个可选配置项，缺省时用默认值，取值必须是正整数，非法时按既有 `ConfigError` 约定启动失败并点名配置项：

| 配置项 | 默认值 | 含义 |
|---|---|---|
| `WORKSPACE_MAX_FILE_BYTES` | `262144` | 单文件字节上限（256 KB） |
| `WORKSPACE_MAX_FILES` | `200` | 单会话文件数上限 |
| `WORKSPACE_MAX_TOTAL_BYTES` | `10485760` | 单会话总字节上限（10 MB） |

- **理由**：配额是运维策略，部署后可能需要在不改代码的前提下调整，符合项目既有的「环境变量配置 + 启动期校验」取向。单文件上限同时用作读取上限（见 spec 中「读取超过上限的文件」）。
- **备选**：硬编码常量（被排除：上线后调整需要改代码）；写进 Agent instruction（被排除：配额是服务端强制约束，交给模型判断无法保证）。

### 8. 打包下载用标准库 `zipfile` 在内存中生成

- **接口**：`GET /api/workspace/download`，参数为用户标识与会话标识；成功返回 `application/zip` 与 `Content-Disposition: attachment`，文件名用会话标识前缀（ASCII，如 `workspace-<前8位>.zip`）。
- **空沙箱与会话不存在**：均返回 404 与明确的中文提示，供前端直接展示，而不是给一个空压缩包。
- **理由**：配额上限已经把单会话规模压到 10 MB 量级，内存打包无需流式；标准库零依赖，符合项目「引入依赖需谨慎」的取向。
- **备选**：引入流式打包库（被排除：新增依赖，收益在当前配额下不存在）；改为逐文件下载（被排除：与"一键取走整套"的目标不符）。

### 9. 前端按钮复用既有下载实现，放在顶栏状态区

- **做法**：在顶栏与会话标识同排新增「下载整个项目」按钮；点击后用 `fetch` 请求下载接口，成功时复用既有 `saveAsFile()` 的 Blob + `<a download>` 方式落盘，失败时读取响应里的中文提示并展示。
- **理由**：顶栏不随消息滚动，入口始终可见；复用现有下载函数可避免重复代码。用 `fetch` 而非直接 `<a href>` 是为了能区分「空沙箱」这类明确提示与真正的下载。
- **备选**：`<a href>` 直链（被排除：空沙箱时会下载到错误内容，无法给出提示）；放在每条回复下方（被排除：同一会话多次生成会有多个入口，语义混乱）。

## Risks / Trade-offs

- [模型不稳定触发 function call，功能形同虚设] → 真机验收把「是否稳定调用工具」作为首要验证项，覆盖当前 `.env` 配置的模型；若不可用，退路是保留「仅前端把多个代码块打包下载」的形态（即 proposal 中的备选路线，不涉及本变更的沙箱部分）。
- [一轮内「文本 → 工具 → 文本」的帧序列导致前端重复或跳变] → 决策 5 已把完整帧改为流结束产出；单元测试必须覆盖这种交替序列，并断言完整帧只有一个。
- [模型写入的内容与它在回复里的声称不一致] → 不做内容校验（见 Non-Goals），使用者可通过打包下载核对；属可接受的演示级取舍。
- [沙箱长期增长无法回收] → 由配额上限封顶；当前历史会话不支持删除，故无清理机制，记入 README 已知限制。
- [同一会话并发请求互相覆盖文件] → 不引入文件锁；并发写同一路径时以后写者为准，记为已知限制。
- [模型借文件工具输出本应拒答的内容] → 提示词明确工具不得用于被拒答的内容，spec 中已有对应 Scenario；验收时专门验证领域外与法规风险请求不落盘。
- [下载接口可被枚举其他会话] → 接口与全站一样无鉴权，仅按用户标识与会话标识查询；沿用既有「无鉴权、仅用于演示」的已知限制，不做本变更范围内的权限体系。

## Migration Plan

1. 配置层：新增三个配额配置项与正整数校验。
2. 新增 `app/services/workspace.py`：沙箱路径解析、路径安全校验、配额校验、四个文件操作、列出沙箱文件、打包。
3. 新增 `app/agent/tools.py`：四个函数工具（从 `tool_context` 取会话标识），装配进 `root_agent`。
4. 改造 `app/services/chat.py`：完整帧改在事件流结束后产出。
5. 新增 `app/api/workspace.py` 的打包下载接口并注册路由。
6. 提示词补工具使用规则（何时调用、相对路径、不重复写、不越既有边界）。
7. 前端顶栏新增「下载整个项目」按钮。
8. 补单元测试并跑通；再真机验收：生成多文件项目并落盘、打包下载、路径逃逸被拒、超配额被拒、增量修改、领域外与法规风险请求不落盘。

回滚：删去 `tools` 装配与下载接口即可退回「纯文本 + 逐块另存为」的形态；`FrameBuilder` 的改动可独立回退，二者互不依赖。

## Open Questions

- 沙箱根目录是否要改为可配置项（便于把 `data/` 挂到独立数据盘）——本版固定为 `data/workspace/`，部署章节按此说明即可。
- 会话删除与沙箱清理策略——待历史会话支持删除后再一并设计。
- 是否需要「已生成文件清单」界面——本版只做整包下载，清单留待后续。