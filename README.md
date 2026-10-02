# 代码辅助智能体（demo）

基于 Python + Google ADK 的网页版代码助手：在浏览器里用自然语言提问，获得**代码生成 / 代码解释 / 重构优化 / 缺陷排查**四类结果，回答以流式方式逐步呈现，代码块带语言标识与语法高亮，可一键复制。覆盖 Java、Python、C#、C++、HTML、JavaScript。对话默认落盘保存，刷新页面或重启服务后仍可回看历史会话。

## 环境要求

- Python 3.10 及以上（本机建议 `py -3.12`）
- 可访问所选模型端点的网络（demo 默认用智谱 `glm-4.5-flash`，完全免费）

## 安装

```powershell
py -3.12 -m venv .venv
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
```

## 配置

1. 到 <https://open.bigmodel.cn> 注册并创建 API Key（免费模型 `glm-4.5-flash` 无需付费）。
2. 复制配置样例并填入真实值：

```powershell
Copy-Item .env.example .env
```

3. 编辑 `.env`：

| 变量 | 说明 |
| --- | --- |
| `LLM_BASE_URL` | OpenAI 兼容端点地址，**需带版本路径**（智谱为 `https://open.bigmodel.cn/api/paas/v4`） |
| `LLM_MODEL` | 模型标识，智谱免费模型为 `glm-4.5-flash` |
| `LLM_API_KEY` | 访问凭据，不要提交到版本库 |
| `APP_HOST` / `APP_PORT` | 服务监听地址，默认 `127.0.0.1:8000` |
| `SESSION_BACKEND` | `sqlite`（默认，落盘到 `data/sessions.db`，刷新与重启后仍有历史）或 `memory`（仅进程内，重启即丢） |

切换模型只需改 `LLM_MODEL` 与 `LLM_BASE_URL`，代码无需改动。`.env` 已被 `.gitignore` 忽略。

## 启动

```powershell
& ".venv\Scripts\python.exe" run.py
```

浏览器访问 <http://127.0.0.1:8000>。配置缺失或格式非法时，启动会直接失败并在终端指出具体配置项名称。

## 使用

- 在输入框描述需求或粘贴代码，`Ctrl + Enter` 或点击「发送」提交。
- 「目标语言」下拉可选择 Java / Python / C# / C++ / HTML / JavaScript；保持「自动推断」时由模型按问题语义判断，语义不足时会先向你确认。
- 回答流式出现；代码块显示语言徽标，并提供「复制」与「另存为」两个按钮。另存为按语言自动命名（Java → `.java`、Python → `.py`、C# → `.cs`、C++ → `.cpp`、HTML → `.html`、JavaScript → `.js`，未标注语言为 `.txt`），同一轮里出现多个同语言代码块时自动加序号（如 `snippet-2.py`）。
- **缺陷排查**：粘贴代码并问「这段代码有什么问题」「帮我找 bug」「哪里会优化」，助手会按严重程度给出问题清单（定位、触发条件、后果）、修复后的完整代码与改动说明；代码确实没问题时会如实说明，不会硬凑问题。
- **意图边界**：只回答代码与编程领域的问题。与代码无关的提问会得到固定回复「我是代码和编程领域的智能体，暂时不能回复其他领域的问题……」，不会顺着话题展开；涉及法律法规与安全合规风险的提问（例如探测、攻击公开网络服务或政府网站）一律拒答，但**防御性安全编程照常作答**（SQL 注入与 XSS 防护、密码哈希、输入校验、权限校验等）。
- **澄清追问上限**：信息不足时助手会先追问（一次最多 3 个问题，或给选项让你选）。追问轮次由服务端按会话记录计数，最多 5 次；达到上限后不再请求模型，直接回复结束语并结束这一串追问，你可以换一种说法重新描述，或点击「新建会话」开始新对话。追问用的内部控制标记不会出现在页面上，刷新后也不会出现在历史记录里。
- **会话标识**：顶栏右侧显示当前会话 ID（等宽字体、可选中复制），方便排障；尚未创建会话时显示「新会话（尚未创建）」。
- 需要对比多个对象或多个并列说明时，助手会优先用 Markdown 表格呈现（例如两种实现方案、多种语言特性对照）。
- **历史会话**：对话自动保存。刷新页面会自动回到上一次所在会话；顶栏「历史会话」按钮可展开列表（显示标题、更新时间与消息数）并切换到任意历史会话。「新建会话」清空当前对话，新会话在发出第一条消息后进入列表。
- 会话数据存在 `data/sessions.db`（SQLite）。想清空全部历史，停止服务后删除该文件即可；把 `SESSION_BACKEND` 改为 `memory` 则不再落盘。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/chat` | 流式对话，`text/event-stream`，帧类型见下 |
| `POST` | `/api/sessions` | 新建会话，返回 `session_id` |
| `GET` | `/api/sessions` | 历史会话列表（`session_id` / `title` / `updated_at` / `message_count`），按最近更新倒序，最多 50 条 |
| `GET` | `/api/sessions/{session_id}` | 查询会话是否存在 |
| `GET` | `/api/sessions/{session_id}/messages` | 该会话的历史消息（`role` + `text`），按发生顺序；会话不存在返回 404 |

SSE 帧协议（仅 `data:` 行，JSON 载荷）：

```text
{"type":"text","data":"<增量文本>","partial":true}    # 增量；最终一帧 partial=false，data 为该轮完整文本
{"type":"error","data":{"code":"auth_error","message":"..."}}
{"type":"done","data":{"session_id":"...","message_id":"..."}}
```

`error` 帧的 `code` 取值：`auth_error`（凭据被拒）、`network_error`（端点不可达）、`upstream_error`（端点返回错误响应）。

## 测试

```powershell
& ".venv\Scripts\python.exe" -m pytest
```

覆盖配置校验（完整配置 / 缺 `LLM_API_KEY` / `base_url` 缺版本路径 / 端口非法）、事件帧转换（增量文本 / 最终完整帧 / 异常与错误事件归类）、历史还原（多轮消息顺序与角色、跳过流式中间态与错误事件、不泄漏模型推理），以及本次新增的追问轮次推导、澄清标记剥离与内部前缀还原（覆盖标记被切片、首字符为 `[` 的普通回复、整段一次性返回、中间插入实质回答后计数归零等情形）。

## 目录结构

```text
app/
├─ main.py            FastAPI 装配、lifespan、静态托管
├─ config.py          环境变量读取与校验
├─ schemas.py         请求/响应、历史消息与 SSE 帧模型
├─ agent/             root_agent / model（LiteLlm）/ prompt
├─ services/          runner（Runner、会话后端与会话查询）、chat（Event → SSE 帧、历史还原）
└─ api/               chat（SSE 对话）、sessions（会话新建/列表/历史消息）
prompts/system.md     系统提示词
web/                  index.html / styles.css / app.js
tests/                单元测试
data/sessions.db      会话落盘文件（首次启动时生成，已被 .gitignore 忽略）
run.py                启动脚本
```

## 已知限制

- 前端通过 CDN（cdnjs）引入 `marked`、`highlight.js`、`DOMPurify`，**离线或该 CDN 被拦截时不可用**：此时页面自动退化为纯文本展示（对话与复制仍可用），但不会渲染 Markdown、也不会有语法高亮。如需离线，把三个库下载到 `web/vendor/` 并改为本地引用（注意 jsdelivr 在部分网络下不可达，cdnjs 与 unpkg 实测可用）。
- 未标注语言的代码块只做等宽展示，不做语法高亮猜测。
- 会话默认落盘到 `data/sessions.db`；由 `memory` 切到 `sqlite` 后，此前只存在于内存中的会话不会迁移。历史列表为逐会话读取（标题与消息数需按会话取出事件推导），故按最近更新倒序并限制 50 条。
- 「历史会话」面板只支持浏览与切换，暂不支持重命名、删除与搜索。
- LiteLLM 会尝试联网拉取模型价格表，网络受限时已在 `run.py` 中改用内置表（`LITELLM_LOCAL_MODEL_COST_MAP=True`）。
- 无鉴权、无多租户与限流，仅用于本地演示；不要把服务直接暴露到公网。
- 免费模型 `glm-4.5-flash` 偶发以英文作答；模型推理（thought）已在服务端过滤，不会出现在回答或历史记录中。
- 澄清追问依赖模型按提示词约定在回复第一行输出内部控制标记 `[[CLARIFY]]`。若模型未输出，该轮不计入追问次数、上限不会推进；若模型在正常回答里误输出该标记，该轮可能被误计为一次追问。标记本身始终不会展示给使用者（流式切片也会被剥离）。
- 达到追问上限那一轮的回复由服务端直接生成，并用会话服务补写进会话；若补写失败会退化为该轮不入库，此时刷新页面看不到最后一轮，但不影响刚收到的回复内容。
- 意图边界（领域外固定回复、法规风险拒答）与表格输出偏好都由提示词约束，属于模型判断而非关键词过滤，边界个例可能超出预期。
- 未接入代码执行沙箱、文件读写工具与仓库级索引；缺陷排查依靠提示词与模型判断，不做静态分析或编译检查。