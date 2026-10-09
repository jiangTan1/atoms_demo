# 网页应用生成智能体（demo）

基于 Python + Google ADK 的**对话式网页应用生成器**：用自然语言描述你想要的网页应用（例如「做一个俄罗斯方块小游戏」），智能体会把构成该应用的 HTML / CSS / JS 文件真实写入服务端沙箱，并在对话界面**右侧即时预览**、可直接上手操作。生成之后可以继续用对话改功能或加需求，每轮改动会自动留下一个版本、随时回滚；也可以为某个版本生成**公开只读分享链接**，发给任何人免登录打开。

访问服务需要先注册或登录（**首个管理员在首次启动时用 `.env` 里的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 指定**，不再是固定的 `root` / `root`）；各人的会话与文件沙箱互相隔离，对话默认落盘保存，刷新页面或重启服务后仍可回看自己的历史会话。

## 能做什么

| 能力 | 说明 |
| --- | --- |
| 描述需求即生成应用 | 说清想要什么，智能体把应用文件写入沙箱，并说明它做了什么、如何操作 |
| 内置示例即选即预览 | 顶栏「示例应用」提供俄罗斯方块 / 贪吃蛇 / 2048 / 计算器四个成品模板，选择后立刻可预览，不依赖实时生成 |
| 生成过程可控 | 执行中显示进度（正在生成第 N 行 · 已用 M 秒），可主动中断；单轮 240 秒超时或被中断后给出失败说明与「重试」按钮 |
| 即时预览 | 对话界面右侧是应用预览区，生成或修改后刷新即可看到最新效果，可直接操作应用 |
| 对话式迭代 | 在后续对话里要求改样式、调数值、加功能，智能体基于沙箱内现有文件做增量修改 |
| 版本回滚 | 每轮有效改动自动留档为一个版本；回滚前会先把当前内容留存为新版本，因此回滚可逆 |
| 公开分享 | 为某个版本生成只读链接，任何人无需登录即可打开该版本的应用，可随时撤销 |

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
| `APP_HOST` / `APP_PORT` | 服务监听地址，默认 `127.0.0.1:80`（只监听回环，公网访问统一走 Nginx） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | **首个管理员的凭据**。仅在首次启动且 `data/users.db` 为空账号库时使用，缺失或非法会启动失败并点名该项；账号库非空后可以留空。用户名与密码均为 3 到 20 个字符，请使用自己的强口令 |
| `SESSION_BACKEND` | `sqlite`（默认，落盘到 `data/sessions.db`，刷新与重启后仍有历史）或 `memory`（仅进程内，重启即丢） |
| `WORKSPACE_MAX_FILE_BYTES` | 可选。会话沙箱**单文件字节上限**，默认 `262144`（256 KB）；同时用作读取单文件的上限 |
| `WORKSPACE_MAX_FILES` | 可选。**单会话文件数上限**，默认 `200` |
| `WORKSPACE_MAX_TOTAL_BYTES` | 可选。**单会话沙箱总占用上限**，默认 `10485760`（10 MB） |
| `VERSION_MAX_PER_SESSION` | 可选。**单会话保留的版本数量上限**，默认 `20`；超过上限时按最旧优先清理 |
| `CHAT_TIMEOUT_SECONDS` | 可选。**单轮生成的时限（秒）**，默认 `240`；超过即主动中止本轮并给出可重试的失败提示。应小于 Nginx 的 `proxy_read_timeout`（`deploy/nginx.conf` 为 300s） |
| `AUTH_COOKIE_SECURE` | 可选。为 `true` 时登录态 Cookie 带 `Secure`（仅 HTTPS 下浏览器才会回传），默认 `false`。**部署到 HTTPS 后应改为 `true`** |

上面几个「上限项」都可以不填；填了必须是正整数，非法时启动会失败并指出具体项名称。`AUTH_COOKIE_SECURE` 可填 `true` / `false` 等常见布尔写法（`1` / `0` / `yes` / `no` / `on` / `off`），非法取值同样启动失败并点名该项。

切换模型只需改 `LLM_MODEL` 与 `LLM_BASE_URL`，代码无需改动。`.env` 已被 `.gitignore` 忽略。

## 启动

```powershell
& ".venv\Scripts\python.exe" run.py
```

浏览器访问 <http://127.0.0.1>（默认端口 80，可省略）。配置缺失或格式非法时，启动会直接失败并在终端指出具体配置项名称。

## 登录与账号

访问服务会先停在认证界面，**注册或登录后才能使用**。未登录时所有业务接口都返回 401 与中文提示，界面上不出现对话区。

- **首个管理员**：由 `.env` 中的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 指定（角色为管理员）。**首次启动且 `data/users.db` 为空账号库时创建**；未配置这两项而账号库为空时，启动会失败并提示缺失的配置项。账号库非空后不再读取这两项，已创建的管理员不会被覆盖、重置或重建（改过的密码不会被配置值冲掉）。
- **自助注册**：填写用户名与密码，两者均为 **3 到 20 个字符**（按去除首尾空白后的长度计）。注册产生的一律是**普通用户**，不具备用户管理权限。
- **注册上限**：普通用户最多 **99 个**。该名额只统计自助注册的账号，内置管理员与管理员新增的账号不占名额；达到上限后新的注册会被拒绝并提示。
- **登录态**：登录成功后服务端签发随机令牌并放进 **HttpOnly Cookie**，有效期 **1 天**；对话界面顶栏显示当前用户名，并提供「修改密码」与「退出登录」两个入口。
- **修改密码**：改密只对已登录用户开放。登录后在对话界面顶栏点「修改密码」，填写原密码与新密码即可。认证界面上的「修改密码」按钮仅作入口提示——未登录时不做改密，点击它只会提示需要先登录。校验通过后该账号**其他已登录的会话立即失效**（发起改密这一处保持有效）。
- **会话与沙箱按登录用户隔离**：会话与文件沙箱归属于创建它们的登录用户，使用者只能列出、读取、继续与下载自己的会话。归属一律取自登录态，请求里携带的 `user_id` 会被忽略；他人的会话标识按「不存在」处理（404），不透露其是否存在。
- **账号库**：`data/users.db`（SQLite），与 `data/sessions.db` 相互独立——把 `SESSION_BACKEND` 改成 `memory` 时账号依然持久化。
- **管理员的新增 / 重置密码 / 删除用户目前只有接口，没有界面**，用法见下方示例。

### 管理员接口示例

管理员操作需要带上登录后的 Cookie。PowerShell（Windows 本机）用 `-WebSession` 保存登录态即可：

```powershell
# 1. 以管理员登录，登录态 Cookie 存入会话变量 $admin（用户名/密码为你在 .env 里配置的首个管理员）
$admin = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod -Uri "http://127.0.0.1/api/auth/login" -Method Post `
  -ContentType "application/json" -WebSession $admin `
  -Body '{"username":"admin","password":"your-strong-password"}'

# 2. 新增用户（来源记为 admin，不占用自助注册的 99 个名额）
Invoke-RestMethod -Uri "http://127.0.0.1/api/auth/users" -Method Post `
  -ContentType "application/json" -WebSession $admin `
  -Body '{"username":"alice","password":"alice-pw"}'

# 3. 重置任意用户的密码（无需其原密码；重置后该用户的全部登录态失效）
Invoke-RestMethod -Uri "http://127.0.0.1/api/auth/users/alice/password" -Method Post `
  -ContentType "application/json" -WebSession $admin `
  -Body '{"password":"new-pw-123"}'

# 4. 删除用户（删除内置管理员会被拒绝）
Invoke-RestMethod -Uri "http://127.0.0.1/api/auth/users/alice" -Method Delete -WebSession $admin
```

Linux / macOS 下把 Cookie 存进文件再用 `-b` 带上即可：

```bash
curl -s -c cookie.txt -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your-strong-password"}' http://127.0.0.1/api/auth/login

curl -s -b cookie.txt -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"alice-pw"}' http://127.0.0.1/api/auth/users
```

## 使用

### 生成与修改应用

- 在输入框描述你想要的网页应用（如「做一个俄罗斯方块小游戏」「做一个能算账的记账页面」），`Ctrl + Enter` 或点击「发送」提交。
- 智能体会把构成应用的文件真实写入服务端一块**按会话隔离的沙箱目录** `data/workspace/<会话ID>/`，并在回复里说明这个应用做了什么、怎么操作、有哪些已知限制。
- **应用产物约定**：入口固定为沙箱内的 `index.html`；样式与脚本用**相对路径**引用，且同样落在沙箱内。整套文件**不需要安装依赖或执行构建**就能在浏览器里直接运行。
- **继续对话即可改**：要求「把下落速度调快一点」「加一个计分板」时，智能体会先读取沙箱内现有文件，再做增量修改，其余功能保持可用；不会无视既有内容另起一个不相关的新应用。
- **下载整个项目**：顶栏「下载整个项目」把当前会话沙箱内的全部文件打包成 zip（**保留目录结构**），用于取走源码。会话还没有生成文件时会提示「暂无可下载的内容」。
- **沙箱边界**：沙箱只用于读写文件，智能体**不能**执行命令、安装依赖、访问网络或读写沙箱之外的文件；生成的应用也**不具备**联网、写服务器文件等沙箱之外的能力，回复里会如实说明。
- **先出骨架、再增量填充**：复杂需求不会被一次性塞给模型。智能体会先写入 `index.html` 骨架，再逐个补 `style.css` / `app.js`，内容多的再分批写，既避免超出单次生成长度上限，也让「生成中」的过程可预期。
- **完整外壳**：生成的应用自带页面外壳——顶栏标题、卡片式内容容器、必要的侧边导航，以及窄屏可用的响应式布局，打开就是一个成形的页面而不是裸控件；样式与脚本都在沙箱内自包含，不依赖任何外部 CSS 框架。

### 生成过程中的进度、中断与重试

- **执行中可见**：生成期间输入框上方的状态区持续显示「正在生成第 N 行 · 已用 M 秒」（还没收到文本时显示「正在等待模型响应」），让你知道后台确实在推进。
- **单轮时限 240 秒**：一轮生成从发起到本轮 SSE 结束受 `CHAT_TIMEOUT_SECONDS`（默认 240）约束。超时由服务端**主动中止**本轮，回复里给出失败说明与「重试」按钮；此时**不会**留下半成品的版本快照，也不会把不完整内容当成本轮成品。
- **主动中断**：生成期间右侧会出现红色的「中断」按钮，点击即断开本轮请求、取消后台生成（模型调用随之中止）。已写入沙箱的部分内容会保留，可重新发送补齐。
- **重试**：因超时、上游限流或网络异常导致本轮失败时，失败提示旁都有「重试」按钮，点击会把**同一条消息原样重发**。主动中断不提供重试按钮（是你自己取消的），直接重新发送即可。
- **诚实报错**：模型调用包在异常处理里，上游限流（HTTP 429 / `rate limit` / `quota exceeded` 等）与调用超时会被识别成对应说明（「触发了限流，请稍后重试」「调用模型端点超时」），并附上原始错误信息，不做静默重试或含糊其辞。

### 示例应用（免生成，即选即预览）

- 顶栏「示例应用」打开一个内置示例列表：**俄罗斯方块、贪吃蛇、2048、计算器**。这些都是**已经写好并验证过的成品模板**，选择后会立刻新建一个会话并把模板文件写入沙箱，右侧预览随即显示可操作的应用，**完全不依赖实时模型生成**。
- 示例模板放在版本库里的 `templates/examples/<示例 ID>/`（含 `index.html` + `style.css` + `app.js`），清单登记在 `templates/examples/manifest.json`。
- 选用示例后会切到该新建会话，之后**和智能体生成的应用完全一样**：可以继续对话修改、留版本、回滚、分享、打包下载。
- 选用示例是「新建会话惰性创建」的唯一例外——它会立即落库并写好沙箱，这样才可能「点开即预览」；复制失败时会回退（删除刚建的空会话并清掉沙箱），不留半初始化状态。

### 预览

- 对话界面右侧是**应用预览区**：每轮回复结束后自动刷新，也可以点「刷新」手动重新加载。
- 预览把沙箱目录当静态站点根提供，入口就是 `index.html`；**应用的键盘与鼠标交互、动画与样式都在预览里正常生效**。
- 预览区状态会区分三种情况：**尚无应用**（还没生成，或沙箱内缺少入口文件 `index.html`）、**加载失败**（服务异常，对话区仍可继续使用）、**登录态失效**（回到认证界面提示重新登录）。不会出现白屏或空白区域。
- 切换历史会话时预览跟随切换，不残留上一段会话的应用。

### 版本与回滚

- 顶栏「版本」打开当前会话的版本列表：**每轮对话改动了沙箱内容后自动留档**为一个版本，按时间倒序展示（最新在最上面）。没有改动的纯问答不产生版本。
- 点某个版本的「回滚到该版本」并确认后，沙箱恢复成该版本的完整内容，预览同步刷新。回滚**不会删除**被跨过的历史版本，列表条目数也不因回滚而减少。
- 回滚前会**先把当前内容留存为新版本**，所以想回到回滚前，只需再选一次那个新版本。
- 单会话版本数量有上限（`VERSION_MAX_PER_SESSION`，默认 20），超出后按最旧优先清理，磁盘占用不会无界增长。

### 分享

- 顶栏「分享」打开分享弹层：选一个版本点「生成分享链接」，链接会**自动复制**到剪贴板；弹层同时列出你在该会话下已创建的分享，可再次复制或「撤销」。
- 分享链接**面向公开**：拿到链接的任何人**无需登录**即可打开该版本的应用并正常操作，但**只能看**——不能用对话、不能下载，也看不到你的会话标识、版本列表与历史消息。
- 分享内容取自**版本快照**而不是当前沙箱：链接指向哪个版本就一直是那个版本，之后你继续对话改应用**不会**改变已发出的分享内容。
- 撤销后原链接立即失效，访问会看到「分享不存在或已失效」的中文提示页。

### 回答呈现与其它

- 回答以流式方式逐步出现；回复里的代码块显示语言徽标，并提供「复制」与「另存为」两个按钮。「另存为」按代码块标注的语言自动命名（如 JavaScript → `.js`、HTML → `.html`），未标注语言时存为 `.txt`，同一轮里出现多个同语言代码块会自动加序号（如 `snippet-2.js`）。**它只是把页面上这一段代码存成单个文件**，与服务端沙箱无关。
- **职责范围**：只处理网页应用相关需求。与网页应用无关的提问会得到固定回复「我是一个网页应用生成智能体，只能根据需求生成和修改网页应用……」，不会顺着话题展开；涉及法律法规与安全合规风险的提问（例如探测、攻击公开网络服务或政府网站）一律拒答，且不把该类内容写入沙箱。
- **澄清追问上限**：信息不足时（例如玩法规则未定）助手会先追问（一次最多 3 个问题，或给选项让你选）。追问轮次由服务端按会话记录计数，最多 5 次；达到上限后不再请求模型，直接回复结束语并结束这一串追问，你可以换一种说法重新描述，或点击「新建会话」开始新对话。追问用的内部控制标记不会出现在页面上，刷新后也不会出现在历史记录里。
- **会话标识**：顶栏右侧显示当前会话 ID（等宽字体、可选中复制），方便排障；尚未创建会话时显示「新会话（尚未创建）」。
- **界面主题**：顶栏「主题」按钮在**自动 / 浅色 / 深色**间循环（选择记在本机），「自动」时跟随系统设置。整个助手界面（认证页、对话页、弹层）共用一套设计令牌——统一的间距、圆角、字号层级与配色，深色下代码高亮样式也随之一同切换。生成的应用本身是浅色自包含页面，预览画布固定为白底，不随界面主题变暗。
- 需要对比多个对象或多个并列说明时，助手会优先用 Markdown 表格呈现。
- **历史会话**：对话自动保存。刷新页面会自动回到上一次所在会话；顶栏「历史会话」按钮可展开列表（显示标题、更新时间与消息数）并切换到任意历史会话。「新建会话」清空当前对话，新会话在发出第一条消息后进入列表。列表与历史消息**只含当前登录用户自己的会话**。
- 数据落盘位置：会话 `data/sessions.db`、账号 `data/users.db`、分享记录 `data/shares.db`、文件沙箱 `data/workspace/`、版本快照 `data/versions/`。想清空全部历史，停止服务后删除这些文件与目录即可；把 `SESSION_BACKEND` 改为 `memory` 则会话不再落盘，但账号、分享与沙箱不受影响。

## 接口

除 `POST /api/auth/register`、`POST /api/auth/login`、`GET /api/auth/me` 与 `/share/{token}/...` 这组免登录的分享预览外，**所有接口都要求有效的登录态**，未登录一律返回 401 与中文提示。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/register` | 自助注册（普通用户，受 99 个名额约束），返回提示文字 |
| `POST` | `/api/auth/login` | 登录；凭据正确时下发 HttpOnly Cookie，返回 `username` / `role` |
| `GET` | `/api/auth/me` | 当前登录身份；未登录返回 401 |
| `POST` | `/api/auth/logout` | 退出登录，吊销当前登录态并清除 Cookie |
| `POST` | `/api/auth/password` | 修改自己的密码（需正确原密码），成功后吊销该用户其他登录态 |
| `POST` | `/api/auth/users` | 仅管理员：新增用户 |
| `POST` | `/api/auth/users/{username}/password` | 仅管理员：重置指定用户密码 |
| `DELETE` | `/api/auth/users/{username}` | 仅管理员：删除用户（内置管理员不可删） |
| `POST` | `/api/chat` | 流式对话，`text/event-stream`，帧类型见下；单轮受 `CHAT_TIMEOUT_SECONDS` 约束，超时中止并回 `error` 帧 |
| `GET` | `/api/examples` | 列出内置示例应用（`id` / `name` / `description`），不请求模型 |
| `POST` | `/api/examples/apply` | 选用一个示例：新建会话并把模板复制进沙箱，返回 `session_id` 与提示；示例不存在返回 404，写入失败返回 500 并回退刚建的空会话 |
| `POST` | `/api/sessions` | 新建会话，返回 `session_id` |
| `GET` | `/api/sessions` | 当前用户的历史会话列表（`session_id` / `title` / `updated_at` / `message_count`），按最近更新倒序，最多 50 条 |
| `GET` | `/api/sessions/{session_id}` | 查询该会话是否存在（非本人会话按不存在处理） |
| `GET` | `/api/sessions/{session_id}/messages` | 该会话的历史消息（`role` + `text`），按发生顺序；会话不存在返回 404 |
| `GET` | `/api/workspace/download?session_id=...` | 把该会话沙箱内的全部文件打包为 zip 下载（`application/zip`，保留目录结构）；沙箱为空或会话不存在返回 404 与中文提示 |
| `GET` | `/api/sessions/{session_id}/preview-token` | 为自己的会话换取预览票据，返回 `token` / `url` / `expires_in`；缺少入口文件时返回 404 与中文提示 |
| `GET` | `/preview/{session_id}/{token}/` | 会话内预览入口页（沙箱的 `index.html`）；票据无效或过期返回 403 与中文提示 |
| `GET` | `/preview/{session_id}/{token}/{路径}` | 按相对路径取沙箱内的预览资源（正确 `Content-Type`）；拒绝路径逃逸与隐藏文件 |
| `GET` | `/api/sessions/{session_id}/versions` | 该会话的版本列表（`version_id` / `created_at`），按时间倒序；无版本时返回空列表 |
| `POST` | `/api/sessions/{session_id}/versions/{version_id}/rollback` | 回滚到指定版本；回滚前先留存当前内容，返回 `preserved_version_id` |
| `POST` | `/api/sessions/{session_id}/shares` | 为指定版本生成公开只读分享，返回 `token` 与可打开的 `url` |
| `GET` | `/api/sessions/{session_id}/shares` | 列出自己在该会话下创建的分享（按创建时间倒序） |
| `DELETE` | `/api/shares/{token}` | 撤销自己创建的分享，原链接立即失效 |
| `GET` | `/share/{token}/` | **免登录**：分享页外壳，用受限 iframe 载入被分享版本；分享不存在或已撤销时返回中文提示页 |
| `GET` | `/share/{token}/app/` | **免登录**：被分享版本的入口页；`/share/{token}/app/{路径}` 取快照内的相对资源 |

对话、会话、版本、预览与分享管理接口的归属一律取自登录态（`user:<登录用户名>`），**不再接受请求体里的 `user_id`**，带上也会被忽略。版本、预览与分享管理接口都会校验会话归属：他人的会话标识按「不存在」处理（404），不透露其是否存在；撤销分享也只作用于自己创建的记录。

免登录的 `/share/{token}/...` 只读取**被分享版本的快照**，不需要也不暴露会话身份与历史；`token` 是 32 字节随机串（`secrets.token_urlsafe(32)`），无法通过枚举猜出。分享页与对话内预览共用同一套安全响应头与 iframe 沙箱能力（见「已知限制」）。

SSE 帧协议（仅 `data:` 行，JSON 载荷）：

```text
{"type":"text","data":"<增量文本>","partial":true}    # 逐片增量；流结束后补一帧 partial=false，data 为该轮完整文本
{"type":"error","data":{"code":"auth_error","message":"..."}}
{"type":"done","data":{"session_id":"...","message_id":"..."}}
```

`partial=false` 的完整帧在**整个事件流结束后**产出一次：挂上文件工具后一轮对话会出现「文本 → 工具调用 → 更多文本」的交替，`partial=false` 的单个事件不再等价于本轮最终回复（见变更 `add-workspace-file-tools` 的 design.md 决策 5）。

`error` 帧的 `code` 取值：`auth_error`（凭据被拒）、`network_error`（端点不可达或调用超时）、`upstream_error`（端点返回错误响应，含 HTTP 429 限流与本轮超时中止）。超时中止时服务端先回一帧 `error`、再回 `done` 让前端收尾，但**不产出** `partial=false` 的完整帧（内容不完整，不能当成品）；此时该轮不计入版本留档。

工具（`write_file` / `read_file` / `list_files` / `delete_file`）的失败——路径非法、超出配额、目标不存在——通过工具结果文本回灌给模型，由模型自行纠正重试或向你说明，**不会**变成 `error` 帧、也不中断本次对话。

## 测试

```powershell
& ".venv\Scripts\python.exe" -m pytest
```

覆盖配置校验（完整配置 / 缺 `LLM_API_KEY` / `base_url` 缺版本路径 / 端口默认 80 与非法端口 / 首个管理员凭据缺省、显式取值与非法长度 / 沙箱配额与版本上限取默认值与非法取值 / `AUTH_COOKIE_SECURE` 缺省与非法取值）、事件帧转换（增量文本 / 聚合事件不重复下发 / 「文本 → 工具调用 → 更多文本」交替只产出一个完整帧 / 异常与错误事件归类）、历史还原（多轮消息顺序与角色、跳过流式中间态与错误事件、不泄漏模型推理）、追问轮次推导、澄清标记剥离与内部前缀还原，沙箱服务（会话隔离、绝对路径与 `..` 与符号链接三类逃逸、三项配额、读写列目录删除、入口定位、快照与恢复、打包）与打包下载接口（有文件 / 空沙箱 / 会话不存在），预览接口（返回入口页 / 子目录资源 / 缺少入口文件与空沙箱的中文提示 / 他人会话 404 / 安全响应头 / 隐藏文件与目录路径被拒），版本服务与接口（指纹不变不产版本 / 沙箱改动产版本 / 倒序列出与会话隔离 / 回滚可逆且历史不减 / 上限清理 / 未登录 401），分享服务与接口（建表幂等 / 随机 token 不可解析 / 分享内容锁定所选版本 / 只列本人 / 撤销生效且非创建者被拒 / 免登录可打开且不暴露会话标识 / iframe 沙箱属性与安全响应头 / 持分享链接访问下载接口 401），自动快照挂点（一轮改动恰好一个版本 / 纯问答不产版本 / 内容未变不重复留档 / 版本按会话隔离），账号服务（建表幂等、加盐哈希与定时安全比对、首个管理员初始化与缺失凭据报错、格式约束、注册与 99 上限、凭据校验不可区分、改密、管理员新增/重置/删除、令牌签发校验吊销与改密后其他令牌失效）、认证接口（各接口成功与失败路径、Cookie 属性、管理员与普通用户的权限差异、账号库为空且未配置 `ADMIN_*` 时启动失败）以及访问控制（未登录 401、客户端指定归属者被忽略、会话与下载按登录用户隔离）。

## 部署到云服务器（阿里云 ECS 示例）

单机部署：Nginx 反向代理 + systemd 托管 uvicorn。示例配置在 `deploy/` 下，文件顶部都标注了需要替换的占位符。

### 1. 选型

- **操作系统建议 Ubuntu 24.04 LTS 64 位（x86_64）**：自带 Python 3.12，与本机验证环境一致。Alibaba Cloud Linux 3 也可以用，但其默认 `python3` 是 3.6，需要自行安装 3.12。
- 规格建议 2 vCPU / 4 GB 起。不跑本地模型，但 1C2G 在安装依赖、生成首个回复时会比较吃力。

### 2. 准备运行环境

```bash
sudo apt update && sudo apt install -y python3.12-venv nginx
sudo mkdir -p /opt/atoms-demo && sudo chown "$USER" /opt/atoms-demo

git clone <你的仓库地址> /opt/atoms-demo
cd /opt/atoms-demo
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cp .env.example .env
```

编辑 `.env`，至少要把 `LLM_API_KEY` 换成真实凭据。`data/sessions.db` 与 `data/users.db` 首次启动时自动生成，不需要从本地拷贝。

### 3. 交给 systemd 托管

```bash
sudo cp deploy/code-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now code-assistant
systemctl status code-assistant
journalctl -u code-assistant -f
```

服务以 `www-data` 运行，需要能读到 `.env`、能写会话库与账号库：

```bash
cd /opt/atoms-demo
sudo chown www-data:www-data .env && sudo chmod 600 .env
sudo install -d -o www-data -g www-data data
```

应用只监听 `127.0.0.1:80`，不直接对外，公网访问统一走 Nginx。因为 80 是特权端口，systemd 单元用 `AmbientCapabilities=CAP_NET_BIND_SERVICE` 授权（无需以 root 运行）；`deploy/nginx.conf` 因而不再监听 80，只保留 443（详见该文件头部说明）。

### 4. 反向代理与 HTTPS

```bash
sudo cp deploy/nginx.conf /etc/nginx/conf.d/code-assistant.conf
sudo nano /etc/nginx/conf.d/code-assistant.conf   # 替换 server_name 与证书路径
sudo nginx -t && sudo systemctl reload nginx
```

样例里有两项是流式回复必需的：`proxy_buffering off`（不关掉的话回复会被攒完再一次性吐出，页面上没有打字机效果）和 `proxy_read_timeout 300s`（默认 60s 在长代码场景下会被提前切断）。同时对 `/api/chat` 按来源 IP 限流（20 次/分钟、突发 3 次），并对免登录的 `/share/` 也限流（60 次/分钟、突发 20 次），作为登录之外的第二道防线。

启用 HTTPS 后，把 `.env` 里的 `AUTH_COOKIE_SECURE` 改为 `true`，登录态 Cookie 才会带上 `Secure` 标志（在纯 HTTP 下开这个开关会导致浏览器不回传 Cookie，无法登录）。

### 5. 上线前检查

- 安全组只放行 22 / 443（若用 80 做 HTTP 跳转再放行 80）；应用只监听回环地址，**不需要为应用端口单独放行**。
- 大陆地域用域名走 80/443 需要完成 ICP 备案；未备案可选香港或海外地域。
- 确认 ECS 能出网访问 `.env` 里 `LLM_BASE_URL` 指向的域名。
- **首个管理员务必使用强口令**：在 `.env` 里设置 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（3 到 20 个字符），首次启动时据此创建；不要沿用 `.env.example` 里的示例文本，也不要再用 `root` / `root` 这类弱口令。
- 确认 Nginx 已终止 TLS 并把 `AUTH_COOKIE_SECURE` 置为 `true`，否则登录口令与 Cookie 会以明文经过公网。
- 会话与账号都落在单机 SQLite 上，不要在多台 ECS 上跑同一份 `data/`。

## 目录结构

```text
app/
├─ main.py            FastAPI 装配、lifespan（初始化账号库、按配置创建首个管理员与分享服务）、静态托管
├─ config.py          环境变量读取与校验
├─ schemas.py         请求/响应、认证模型、历史消息、版本与分享模型、SSE 帧模型
├─ agent/             root_agent / model（LiteLlm）/ prompt / tools（四个沙箱文件工具）
├─ services/          runner（Runner、会话后端与会话查询）、chat（Event → SSE 帧、历史还原、单轮时限与失败归类）、workspace（会话沙箱、入口定位、从模板初始化、快照与打包）、examples（内置示例清单与模板复制）、versions（沙箱指纹、按需留档、回滚与上限清理）、shares（分享记录与 token 解析）、accounts（账号库、密码哈希与登录态令牌）
└─ api/               auth（鉴权依赖 + 认证与管理员接口）、chat（SSE 对话，收尾自动留档）、sessions（会话新建/列表/历史消息）、workspace（打包下载）、versions（版本列表与回滚）、preview（会话内应用预览）、shares（分享管理与免登录分享预览）、examples（内置示例列表与选用）
prompts/system.md     系统提示词
templates/examples/   内置示例应用模板（manifest.json + 每个示例的 index.html / style.css / app.js）
web/                  index.html / styles.css / app.js
tests/                单元测试
deploy/               nginx.conf / code-assistant.service（部署样例，见「部署到云服务器」）
data/sessions.db      会话落盘文件（首次启动时生成，已被 .gitignore 忽略）
data/users.db         账号与登录态落盘文件（首次启动时生成，已被 .gitignore 忽略）
data/shares.db        分享记录落盘文件（首次创建分享时生成，已被 .gitignore 忽略）
data/workspace/       各会话的文件沙箱目录（有文件写入时生成，已被 .gitignore 忽略）
data/versions/        各会话的版本快照目录（沙箱有改动时生成，已被 .gitignore 忽略）
run.py                启动脚本（本地开发用，带热重载）
```

## 已知限制

- 前端通过 CDN（cdnjs）引入 `marked`、`highlight.js`、`DOMPurify`，**离线或该 CDN 被拦截时不可用**：此时页面自动退化为纯文本展示（对话与复制仍可用），但不会渲染 Markdown、也不会有语法高亮。如需离线，把三个库下载到 `web/vendor/` 并改为本地引用（注意 jsdelivr 在部分网络下不可达，cdnjs 与 unpkg 实测可用）。
- **预览与分享里的应用运行在「不透明源」中**：iframe 只授予 `allow-scripts` / `allow-forms` / `allow-modals` / `allow-popups` / `allow-pointer-lock`，**不授予** `allow-same-origin`，也**不授予**顶层导航。因此应用脚本读不到主站 Cookie 与 `localStorage`、也不能把主站页面跳走；代价是**应用自身用不了 `localStorage` / `sessionStorage`、同源 `fetch` 与 Cookie**（浏览器会直接抛异常），需要持久化的应用只能用内存变量，刷新后状态重置。纯前端、状态在内存里的应用（游戏、计算器、表单工具等）不受影响。预览响应同时带 `X-Content-Type-Options: nosniff` 与限制资源来源的 CSP（含 `connect-src 'none'`），所以预览内的应用**也发不出网络请求**。
- **预览地址把票据放在路径里而不是靠登录态 Cookie**：不透明源的 iframe 自己发起的子资源请求被浏览器视为跨站，`SameSite=Lax` 的登录 Cookie 不会跟随，会得到 401 并被 Chrome 的 ORB（`net::ERR_BLOCKED_BY_ORB`）拦掉，导致预览里样式与脚本全部失效。因此预览入口为 `/preview/<会话>/<票据>/`，页面内的相对路径自动继承同一前缀的票据，子资源无需 Cookie 即可加载。票据由 `GET /api/sessions/{session_id}/preview-token` 在为本人会话通过归属校验后签发（HMAC 签名、默认有效期 1 小时、绑定会话，见 `app/services/preview_token.py`）。
- **版本快照会占用磁盘**：每个版本是沙箱内容的一份整目录副本，单会话最多保留 `VERSION_MAX_PER_SESSION`（默认 20）份，超出后按最旧优先清理。回滚也会新增一份（先留存当前内容），因此频繁回滚会推进版本并淘汰最旧版本；需要回收空间时停止服务后删除 `data/versions/`。
- **分享是「免登录读入口」的定位**：任何拿到链接的人都能打开该版本的应用，因此**不要把含隐私数据的应用分享出去**。链接不设有效期，只能由创建者撤销；`token` 为 32 字节随机串不可枚举，为缓解枚举与滥用，`deploy/nginx.conf` 已对 `/api/chat` 与 `/share/` 分别按来源 IP 限流。
- **既有会话可能没有入口文件**：本次改造前生成的会话沙箱里通常没有 `index.html`，这些会话在预览区会得到「缺少入口文件 `index.html`」的中文提示（而不是报错）；在对话里让智能体补上入口文件即可预览，历史会话与打包下载不受影响。
- **把预览/分享的应用地址当顶层页面直接打开会绕过 iframe 沙箱**：`/preview/<会话>/<票据>/` 与 `/share/<token>/app/` 在**被 iframe 嵌入**时处在不透明源中（脚本读不到 `document.cookie` 与 `localStorage`，已实测），但如果直接在地址栏打开这两个地址，文档就落在主站源上、不再是浏览器级的源隔离。此时应用脚本仍受响应头 CSP 的 `connect-src 'none'` 约束（发不出 `fetch` / `XMLHttpRequest`，也拿不到 HttpOnly 的登录态 Cookie），但这一层只是「阻止联网」而不是「换一个源」。彻底解决需要把预览迁到独立域名或独立端口（`openspec/changes/add-web-app-builder/design.md` 的 Open Questions 已记录），本版未做。
- **单轮生成有 240 秒硬上限**（`CHAT_TIMEOUT_SECONDS`）：超时会被服务端主动中止并给出可重试的失败提示，该轮**不留版本**，但已写入沙箱的文件仍在。需求过大时请拆成几轮对话分批补，或先用「示例应用」拿到一个成品再改。
- 未标注语言的代码块只做等宽展示，不做语法高亮猜测。
- 会话默认落盘到 `data/sessions.db`；由 `memory` 切到 `sqlite` 后，此前只存在于内存中的会话不会迁移。历史列表为逐会话读取（标题与消息数需按会话取出事件推导），故按最近更新倒序并限制 50 条。
- 「历史会话」面板只支持浏览与切换，暂不支持重命名、删除与搜索。
- LiteLLM 会尝试联网拉取模型价格表，网络受限时已在 `run.py` 与 `deploy/code-assistant.service` 中改用内置表（`LITELLM_LOCAL_MODEL_COST_MAP=True`）。
- **BREAKING：升级后既有匿名会话不再展示**。认证改造前所有会话都以匿名身份（`user_id=web-user`）落盘，改造后归属一律是 `user:<登录用户名>`，因此**旧的会话与沙箱对所有用户都不可见、也不会出现在历史列表里**。数据没有迁移：会话仍在 `data/sessions.db` 中、文件仍在 `data/workspace/` 下，需要取回只能人工处理（例如直接读库或临时改回 `web-user` 归属）。这是有意为之，不做自动迁移与认领。
- **无 HTTPS 时登录口令与 Cookie 明文传输**。默认 `AUTH_COOKIE_SECURE=false` 是为了让本机与内网 HTTP 演示开箱可用；正式部署必须在 Nginx 终止 TLS 后把该项改为 `true`，否则口令与登录态在公网上是明文。
- **首个管理员只由 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 在首次启动时创建，没有固定的默认口令**。账号库非空后这两项不再生效，改过的密码不会被配置值冲掉；若清空了 `data/users.db` 又没填这两项，服务会拒绝启动并提示缺失的配置项。密码下限仍是 3 个字符（偏松，便于演示），本版没有口令复杂度策略、没有登录失败锁定与验证码，请自行使用强口令。
- **管理员的新增 / 重置密码 / 删除用户只有接口、没有界面**。需要按 README「管理员接口示例」手动调用；界面不在本次变更范围内。
- **登录态有效期固定 1 天**，不可配置；也不做「记住我」、登录态续期与多设备管理。
- **用户名区分大小写**，`Alice` 与 `alice` 会被视为两个不同账号，没有做防混淆的归一化。
- 账号库 `data/users.db` 与登录态表随登录次数增长；每次登录前会清理该用户的过期记录，数据量在有界用户数下可忽略。
- 全站已要求登录，但只区分「管理员」与「普通用户」两种角色，没有更细粒度的资源 ACL。`deploy/nginx.conf` 按来源 IP 的限流作为登录之外的第二道防线；不要把 uvicorn 直接暴露到公网。
- 免费模型 `glm-4.5-flash` 偶发以英文作答；模型推理（thought）已在服务端过滤，不会出现在回答或历史记录中。
- 澄清追问依赖模型按提示词约定在回复第一行输出内部控制标记 `[[CLARIFY]]`。若模型未输出，该轮不计入追问次数、上限不会推进；若模型在正常回答里误输出该标记，该轮可能被误计为一次追问。标记本身始终不会展示给使用者（流式切片也会被剥离）。
- 达到追问上限那一轮的回复由服务端直接生成，并用会话服务补写进会话；若补写失败会退化为该轮不入库，此时刷新页面看不到最后一轮，但不影响刚收到的回复内容。
- 意图边界（领域外固定回复、法规风险拒答）与表格输出偏好都由提示词约束，属于模型判断而非关键词过滤，边界个例可能超出预期。
- 文件沙箱与版本快照都不随会话删除而清理：当前历史会话只支持浏览与切换，「新建会话」也不会删除上一段会话的文件，`data/workspace/` 与 `data/versions/` 会随使用逐步累积；需要清空时停止服务后手动删除这两个目录。
- 同一会话并发发起的请求会各自写沙箱，写同一个路径时**以后写者为准**，没有文件锁与冲突检测。
- 打包下载接口已要求登录并校验会话归属：只按登录用户的 `user_id` 查询会话，他人的会话标识按不存在处理（404），因此会话 ID 不再可被枚举来取走他人文件。
- 生成应用依赖模型稳定触发 `function call`。免费模型 `glm-4.5-flash` 实测可用，但能力较弱的模型可能仍只输出文本、不落盘；此时页面上的代码块仍可用「另存为」单个取出，也可以直接把代码复制到本地自行保存为 `index.html`。
- 服务端**不执行**生成的应用代码：文件工具只做沙箱内的读写、列目录与删除，**不会**执行命令、安装依赖或访问网络。应用只在浏览器里运行（对话内预览与分享预览），服务端不做编译、构建或运行校验。
- **预览依赖沙箱内的入口文件 `index.html`**：应用产物不含入口文件时预览区只给出提示、不呈现内容；多页应用需自行把入口页放在沙箱根，并用相对路径引用其它文件。