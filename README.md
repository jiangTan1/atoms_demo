# 代码辅助智能体（demo）

基于 Python + Google ADK 的网页版代码助手：在浏览器里用自然语言提问，获得**代码生成 / 代码解释 / 重构优化 / 缺陷排查**四类结果，回答以流式方式逐步呈现，代码块带语言标识与语法高亮，可一键复制。覆盖 Java、Python、C#、C++、HTML、JavaScript。访问服务需要先注册或登录，登录后各人的会话与文件沙箱互相隔离；对话默认落盘保存，刷新页面或重启服务后仍可回看自己的历史会话。

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
| `WORKSPACE_MAX_FILE_BYTES` | 可选。会话沙箱**单文件字节上限**，默认 `262144`（256 KB）；同时用作读取单文件的上限 |
| `WORKSPACE_MAX_FILES` | 可选。**单会话文件数上限**，默认 `200` |
| `WORKSPACE_MAX_TOTAL_BYTES` | 可选。**单会话沙箱总占用上限**，默认 `10485760`（10 MB） |
| `AUTH_COOKIE_SECURE` | 可选。为 `true` 时登录态 Cookie 带 `Secure`（仅 HTTPS 下浏览器才会回传），默认 `false`。**部署到 HTTPS 后应改为 `true`** |

三个 `WORKSPACE_*` 项都可以不填；填了必须是正整数，非法时启动会失败并指出具体项名称。`AUTH_COOKIE_SECURE` 可填 `true` / `false` 等常见布尔写法（`1` / `0` / `yes` / `no` / `on` / `off`），非法取值同样启动失败并点名该项。

切换模型只需改 `LLM_MODEL` 与 `LLM_BASE_URL`，代码无需改动。`.env` 已被 `.gitignore` 忽略。

## 启动

```powershell
& ".venv\Scripts\python.exe" run.py
```

浏览器访问 <http://127.0.0.1:8000>。配置缺失或格式非法时，启动会直接失败并在终端指出具体配置项名称。

## 登录与账号

访问服务会先停在认证界面，**注册或登录后才能使用**。未登录时所有业务接口都返回 401 与中文提示，界面上不出现对话区。

- **默认管理员**：用户名与密码都是 `root`（角色为管理员）。首次启动且 `data/users.db` 为空账号库时自动创建；库非空时不覆盖，改过的 `root` 密码不会被重置。
- **自助注册**：填写用户名与密码，两者均为 **3 到 20 个字符**（按去除首尾空白后的长度计）。注册产生的一律是**普通用户**，不具备用户管理权限。
- **注册上限**：普通用户最多 **99 个**。该名额只统计自助注册的账号，`root` 与管理员新增的账号不占名额；达到上限后新的注册会被拒绝并提示。
- **登录态**：登录成功后服务端签发随机令牌并放进 **HttpOnly Cookie**，有效期 **1 天**；对话界面顶栏显示当前用户名，并提供「修改密码」与「退出登录」两个入口。
- **修改密码**：改密只对已登录用户开放。登录后在对话界面顶栏点「修改密码」，填写原密码与新密码即可。认证界面上的「修改密码」按钮仅作入口提示——未登录时不做改密，点击它只会提示需要先登录。校验通过后该账号**其他已登录的会话立即失效**（发起改密这一处保持有效）。
- **会话与沙箱按登录用户隔离**：会话与文件沙箱归属于创建它们的登录用户，使用者只能列出、读取、继续与下载自己的会话。归属一律取自登录态，请求里携带的 `user_id` 会被忽略；他人的会话标识按「不存在」处理（404），不透露其是否存在。
- **账号库**：`data/users.db`（SQLite），与 `data/sessions.db` 相互独立——把 `SESSION_BACKEND` 改成 `memory` 时账号依然持久化。
- **管理员的新增 / 重置密码 / 删除用户目前只有接口，没有界面**，用法见下方示例。

### 管理员接口示例

管理员操作需要带上登录后的 Cookie。PowerShell（Windows 本机）用 `-WebSession` 保存登录态即可：

```powershell
# 1. 以管理员登录，登录态 Cookie 存入会话变量 $admin
$admin = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/auth/login" -Method Post `
  -ContentType "application/json" -WebSession $admin `
  -Body '{"username":"root","password":"root"}'

# 2. 新增用户（来源记为 admin，不占用自助注册的 99 个名额）
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/auth/users" -Method Post `
  -ContentType "application/json" -WebSession $admin `
  -Body '{"username":"alice","password":"alice-pw"}'

# 3. 重置任意用户的密码（无需其原密码；重置后该用户的全部登录态失效）
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/auth/users/alice/password" -Method Post `
  -ContentType "application/json" -WebSession $admin `
  -Body '{"password":"new-pw-123"}'

# 4. 删除用户（删除默认管理员 root 会被拒绝）
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/auth/users/alice" -Method Delete -WebSession $admin
```

Linux / macOS 下把 Cookie 存进文件再用 `-b` 带上即可：

```bash
curl -s -c cookie.txt -H 'Content-Type: application/json' \
  -d '{"username":"root","password":"root"}' http://127.0.0.1:8000/api/auth/login

curl -s -b cookie.txt -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"alice-pw"}' http://127.0.0.1:8000/api/auth/users
```

## 使用

- 在输入框描述需求或粘贴代码，`Ctrl + Enter` 或点击「发送」提交。
- 「目标语言」下拉可选择 Java / Python / C# / C++ / HTML / JavaScript；保持「自动推断」时由模型按问题语义判断，语义不足时会先向你确认。
- 回答流式出现；代码块显示语言徽标，并提供「复制」与「另存为」两个按钮。另存为按语言自动命名（Java → `.java`、Python → `.py`、C# → `.cs`、C++ → `.cpp`、HTML → `.html`、JavaScript → `.js`，未标注语言为 `.txt`），同一轮里出现多个同语言代码块时自动加序号（如 `snippet-2.py`）。**它只是把页面上这一段代码存成单个文件**，不涉及服务端。
- **生成项目与文件沙箱**：当你要求生成一个多文件项目时，助手会把各文件真实写入服务端一块**按会话隔离的沙箱目录** `data/workspace/<会话ID>/`，并在回复里给出目录结构与各文件职责。沙箱只用于读写文件，助手**不能**执行命令、安装依赖、访问网络或读写沙箱之外的文件。要求修改已生成的文件时，助手会先读取原文件再写入完整的新版本。
- **下载整个项目**：顶栏「下载整个项目」按钮把当前会话沙箱内的全部文件打包成一个 zip 下载，**保留目录结构**，与代码块上的「另存为」（只存页面上那一段代码）用途不同：前者取走整套项目文件，后者只留一段代码。会话还没有生成文件时会提示「暂无可下载的内容」。
- **缺陷排查**：粘贴代码并问「这段代码有什么问题」「帮我找 bug」「哪里会优化」，助手会按严重程度给出问题清单（定位、触发条件、后果）、修复后的完整代码与改动说明；代码确实没问题时会如实说明，不会硬凑问题。
- **意图边界**：只回答代码与编程领域的问题。与代码无关的提问会得到固定回复「我是代码和编程领域的智能体，暂时不能回复其他领域的问题……」，不会顺着话题展开；涉及法律法规与安全合规风险的提问（例如探测、攻击公开网络服务或政府网站）一律拒答，但**防御性安全编程照常作答**（SQL 注入与 XSS 防护、密码哈希、输入校验、权限校验等）。
- **澄清追问上限**：信息不足时助手会先追问（一次最多 3 个问题，或给选项让你选）。追问轮次由服务端按会话记录计数，最多 5 次；达到上限后不再请求模型，直接回复结束语并结束这一串追问，你可以换一种说法重新描述，或点击「新建会话」开始新对话。追问用的内部控制标记不会出现在页面上，刷新后也不会出现在历史记录里。
- **会话标识**：顶栏右侧显示当前会话 ID（等宽字体、可选中复制），方便排障；尚未创建会话时显示「新会话（尚未创建）」。
- 需要对比多个对象或多个并列说明时，助手会优先用 Markdown 表格呈现（例如两种实现方案、多种语言特性对照）。
- **历史会话**：对话自动保存。刷新页面会自动回到上一次所在会话；顶栏「历史会话」按钮可展开列表（显示标题、更新时间与消息数）并切换到任意历史会话。「新建会话」清空当前对话，新会话在发出第一条消息后进入列表。列表与历史消息**只含当前登录用户自己的会话**。
- 会话数据存在 `data/sessions.db`（SQLite），账号数据存在 `data/users.db`。想清空全部历史，停止服务后删除 `data/sessions.db` 即可（`data/workspace/` 下的沙箱文件需要一并手动删除）；把 `SESSION_BACKEND` 改为 `memory` 则不再落盘，但账号不受影响。

## 接口

除 `POST /api/auth/register`、`POST /api/auth/login`、`GET /api/auth/me` 外，**所有接口都要求有效的登录态**，未登录一律返回 401 与中文提示。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/register` | 自助注册（普通用户，受 99 个名额约束），返回提示文字 |
| `POST` | `/api/auth/login` | 登录；凭据正确时下发 HttpOnly Cookie，返回 `username` / `role` |
| `GET` | `/api/auth/me` | 当前登录身份；未登录返回 401 |
| `POST` | `/api/auth/logout` | 退出登录，吊销当前登录态并清除 Cookie |
| `POST` | `/api/auth/password` | 修改自己的密码（需正确原密码），成功后吊销该用户其他登录态 |
| `POST` | `/api/auth/users` | 仅管理员：新增用户 |
| `POST` | `/api/auth/users/{username}/password` | 仅管理员：重置指定用户密码 |
| `DELETE` | `/api/auth/users/{username}` | 仅管理员：删除用户（`root` 不可删） |
| `POST` | `/api/chat` | 流式对话，`text/event-stream`，帧类型见下 |
| `POST` | `/api/sessions` | 新建会话，返回 `session_id` |
| `GET` | `/api/sessions` | 当前用户的历史会话列表（`session_id` / `title` / `updated_at` / `message_count`），按最近更新倒序，最多 50 条 |
| `GET` | `/api/sessions/{session_id}` | 查询该会话是否存在（非本人会话按不存在处理） |
| `GET` | `/api/sessions/{session_id}/messages` | 该会话的历史消息（`role` + `text`），按发生顺序；会话不存在返回 404 |
| `GET` | `/api/workspace/download?session_id=...` | 把该会话沙箱内的全部文件打包为 zip 下载（`application/zip`，保留目录结构）；沙箱为空或会话不存在返回 404 与中文提示 |

对话与会话接口的归属一律取自登录态（`user:<登录用户名>`），**不再接受请求体里的 `user_id`**，带上也会被忽略。

SSE 帧协议（仅 `data:` 行，JSON 载荷）：

```text
{"type":"text","data":"<增量文本>","partial":true}    # 逐片增量；流结束后补一帧 partial=false，data 为该轮完整文本
{"type":"error","data":{"code":"auth_error","message":"..."}}
{"type":"done","data":{"session_id":"...","message_id":"..."}}
```

`partial=false` 的完整帧在**整个事件流结束后**产出一次：挂上文件工具后一轮对话会出现「文本 → 工具调用 → 更多文本」的交替，`partial=false` 的单个事件不再等价于本轮最终回复（见变更 `add-workspace-file-tools` 的 design.md 决策 5）。

`error` 帧的 `code` 取值：`auth_error`（凭据被拒）、`network_error`（端点不可达）、`upstream_error`（端点返回错误响应）。

工具（`write_file` / `read_file` / `list_files` / `delete_file`）的失败——路径非法、超出配额、目标不存在——通过工具结果文本回灌给模型，由模型自行纠正重试或向你说明，**不会**变成 `error` 帧、也不中断本次对话。

## 测试

```powershell
& ".venv\Scripts\python.exe" -m pytest
```

覆盖配置校验（完整配置 / 缺 `LLM_API_KEY` / `base_url` 缺版本路径 / 端口非法 / 沙箱配额取默认值与非法取值 / `AUTH_COOKIE_SECURE` 缺省与非法取值）、事件帧转换（增量文本 / 聚合事件不重复下发 / 「文本 → 工具调用 → 更多文本」交替只产出一个完整帧 / 异常与错误事件归类）、历史还原（多轮消息顺序与角色、跳过流式中间态与错误事件、不泄漏模型推理）、追问轮次推导、澄清标记剥离与内部前缀还原，沙箱服务（会话隔离、绝对路径与 `..` 与符号链接三类逃逸、三项配额、读写列目录删除、打包）与打包下载接口（有文件 / 空沙箱 / 会话不存在），账号服务（建表幂等、加盐哈希与定时安全比对、默认管理员初始化、格式约束、注册与 99 上限、凭据校验不可区分、改密、管理员新增/重置/删除、令牌签发校验吊销与改密后其他令牌失效）、认证接口（各接口成功与失败路径、Cookie 属性、管理员与普通用户的权限差异）以及访问控制（未登录 401、客户端指定归属者被忽略、会话与下载按登录用户隔离）。

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

应用只监听 `127.0.0.1:8000`，不直接对外，公网访问统一走 Nginx。

### 4. 反向代理与 HTTPS

```bash
sudo cp deploy/nginx.conf /etc/nginx/conf.d/code-assistant.conf
sudo nano /etc/nginx/conf.d/code-assistant.conf   # 替换 server_name 与证书路径
sudo nginx -t && sudo systemctl reload nginx
```

样例里有两项是流式回复必需的：`proxy_buffering off`（不关掉的话回复会被攒完再一次性吐出，页面上没有打字机效果）和 `proxy_read_timeout 300s`（默认 60s 在长代码场景下会被提前切断）。同时对 `/api/chat` 按来源 IP 限流（20 次/分钟、突发 3 次），作为登录之外的第二道防线。

启用 HTTPS 后，把 `.env` 里的 `AUTH_COOKIE_SECURE` 改为 `true`，登录态 Cookie 才会带上 `Secure` 标志（在纯 HTTP 下开这个开关会导致浏览器不回传 Cookie，无法登录）。

### 5. 上线前检查

- 安全组只放行 22 / 80 / 443，**不要开放 8000**。
- 大陆地域用域名走 80/443 需要完成 ICP 备案；未备案可选香港或海外地域。
- 确认 ECS 能出网访问 `.env` 里 `LLM_BASE_URL` 指向的域名。
- **必须修改默认管理员口令**：首次启动会创建 `root` / `root`，登录后请立刻用对话界面顶栏的「修改密码」改掉它。
- 确认 Nginx 已终止 TLS 并把 `AUTH_COOKIE_SECURE` 置为 `true`，否则登录口令与 Cookie 会以明文经过公网。
- 会话与账号都落在单机 SQLite 上，不要在多台 ECS 上跑同一份 `data/`。

## 目录结构

```text
app/
├─ main.py            FastAPI 装配、lifespan（初始化账号库与默认管理员）、静态托管
├─ config.py          环境变量读取与校验
├─ schemas.py         请求/响应、认证模型、历史消息与 SSE 帧模型
├─ agent/             root_agent / model（LiteLlm）/ prompt / tools（四个沙箱文件工具）
├─ services/          runner（Runner、会话后端与会话查询）、chat（Event → SSE 帧、历史还原）、workspace（会话沙箱与打包）、accounts（账号库、密码哈希与登录态令牌）
└─ api/               auth（鉴权依赖 + 认证与管理员接口）、chat（SSE 对话）、sessions（会话新建/列表/历史消息）、workspace（打包下载）
prompts/system.md     系统提示词
web/                  index.html / styles.css / app.js
tests/                单元测试
deploy/               nginx.conf / code-assistant.service（部署样例，见「部署到云服务器」）
data/sessions.db      会话落盘文件（首次启动时生成，已被 .gitignore 忽略）
data/users.db         账号与登录态落盘文件（首次启动时生成，已被 .gitignore 忽略）
data/workspace/       各会话的文件沙箱目录（有文件写入时生成，已被 .gitignore 忽略）
run.py                启动脚本（本地开发用，带热重载）
```

## 已知限制

- 前端通过 CDN（cdnjs）引入 `marked`、`highlight.js`、`DOMPurify`，**离线或该 CDN 被拦截时不可用**：此时页面自动退化为纯文本展示（对话与复制仍可用），但不会渲染 Markdown、也不会有语法高亮。如需离线，把三个库下载到 `web/vendor/` 并改为本地引用（注意 jsdelivr 在部分网络下不可达，cdnjs 与 unpkg 实测可用）。
- 未标注语言的代码块只做等宽展示，不做语法高亮猜测。
- 会话默认落盘到 `data/sessions.db`；由 `memory` 切到 `sqlite` 后，此前只存在于内存中的会话不会迁移。历史列表为逐会话读取（标题与消息数需按会话取出事件推导），故按最近更新倒序并限制 50 条。
- 「历史会话」面板只支持浏览与切换，暂不支持重命名、删除与搜索。
- LiteLLM 会尝试联网拉取模型价格表，网络受限时已在 `run.py` 与 `deploy/code-assistant.service` 中改用内置表（`LITELLM_LOCAL_MODEL_COST_MAP=True`）。
- **BREAKING：升级后既有匿名会话不再展示**。认证改造前所有会话都以匿名身份（`user_id=web-user`）落盘，改造后归属一律是 `user:<登录用户名>`，因此**旧的会话与沙箱对所有用户都不可见、也不会出现在历史列表里**。数据没有迁移：会话仍在 `data/sessions.db` 中、文件仍在 `data/workspace/` 下，需要取回只能人工处理（例如直接读库或临时改回 `web-user` 归属）。这是有意为之，不做自动迁移与认领。
- **无 HTTPS 时登录口令与 Cookie 明文传输**。默认 `AUTH_COOKIE_SECURE=false` 是为了让本机与内网 HTTP 演示开箱可用；正式部署必须在 Nginx 终止 TLS 后把该项改为 `true`，否则口令与登录态在公网上是明文。
- **默认口令 `root` / `root` 与 3 个字符的密码下限属演示级取舍**。下限偏松是便于演示；上线前必须修改默认管理员口令，并按需要自行收紧复杂度要求（本版没有口令复杂度策略、没有登录失败锁定与验证码）。
- **管理员的新增 / 重置密码 / 删除用户只有接口、没有界面**。需要按 README「管理员接口示例」手动调用；界面不在本次变更范围内。
- **登录态有效期固定 1 天**，不可配置；也不做「记住我」、登录态续期与多设备管理。
- **用户名区分大小写**，`Alice` 与 `alice` 会被视为两个不同账号，没有做防混淆的归一化。
- 账号库 `data/users.db` 与登录态表随登录次数增长；每次登录前会清理该用户的过期记录，数据量在有界用户数下可忽略。
- 全站已要求登录，但只区分「管理员」与「普通用户」两种角色，没有更细粒度的资源 ACL。`deploy/nginx.conf` 按来源 IP 的限流作为登录之外的第二道防线；不要把 uvicorn 直接暴露到公网。
- 免费模型 `glm-4.5-flash` 偶发以英文作答；模型推理（thought）已在服务端过滤，不会出现在回答或历史记录中。
- 澄清追问依赖模型按提示词约定在回复第一行输出内部控制标记 `[[CLARIFY]]`。若模型未输出，该轮不计入追问次数、上限不会推进；若模型在正常回答里误输出该标记，该轮可能被误计为一次追问。标记本身始终不会展示给使用者（流式切片也会被剥离）。
- 达到追问上限那一轮的回复由服务端直接生成，并用会话服务补写进会话；若补写失败会退化为该轮不入库，此时刷新页面看不到最后一轮，但不影响刚收到的回复内容。
- 意图边界（领域外固定回复、法规风险拒答）与表格输出偏好都由提示词约束，属于模型判断而非关键词过滤，边界个例可能超出预期。
- 文件沙箱不随会话删除而清理：当前历史会话只支持浏览与切换，「新建会话」也不会删除上一段会话的文件，`data/workspace/` 会随使用逐步累积；需要清空时停止服务后手动删除该目录。
- 同一会话并发发起的请求会各自写沙箱，写同一个路径时**以后写者为准**，没有文件锁与冲突检测。
- 打包下载接口已要求登录并校验会话归属：只按登录用户的 `user_id` 查询会话，他人的会话标识按不存在处理（404），因此会话 ID 不再可被枚举来取走他人文件。
- 生成项目依赖模型稳定触发 `function call`。免费模型 `glm-4.5-flash` 实测可用，但能力较弱的模型可能仍只输出文本、不落盘；此时页面上的代码块仍可用「另存为」单个取出。
- 未接入代码执行沙箱与仓库级索引：文件工具只做沙箱内的读写、列目录与删除，**不会**执行命令、安装依赖或访问网络，写入的代码也不会被运行或校验。