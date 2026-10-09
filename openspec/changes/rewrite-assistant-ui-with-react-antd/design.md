# Design

## Context

动机见 proposal.md 的 Why。本设计基于对当前实现的核实：

- **前端现状**：`web/index.html`（约 200 行）+ `web/styles.css`（设计令牌 + 手写组件样式）+ `web/app.js`（约 1400 行，模块级函数与全局状态）。无 `package.json`、无构建步骤。三个渲染库从 cdnjs 引入：`marked` 12、`DOMPurify` 3.1、`highlight.js` 11.9（含 `github` / `github-dark` 两份主题样式，靠 `link.disabled` 切换）。
- **已实现的交互**（本次必须全部保留）：认证门控（登录 / 注册 / 改密 / 改密弹层）、顶栏（示例应用、历史会话、新建会话、版本、分享、下载整个项目、会话 ID、当前用户、退出、主题三态）、消息区（打字机增量渲染 + 完整帧兜底、Markdown + 高亮 + 代码块「复制 / 另存为」）、执行进度（`正在生成第 N 行 · 已用 M 秒`，500ms 刷新）、主动中断（`AbortController`）、失败重试（同一条消息原样重发）、401 集中处理、预览区（票据路径 `/preview/{会话}/{票据}/…` + `iframe` sandbox）、版本弹层（列表 / 回滚）、分享弹层（生成只读链接）、示例弹层（选择即建会话并写沙箱）。主题选择存在 `localStorage` 的 `code-assistant.theme`，取值 `auto` / `light` / `dark`。
- **服务端托管方式**：`app/main.py` 定义 `WEB_DIR = <repo>/web`，在所有路由注册之后执行 `app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")`；`/api/*`、`/preview/*`、`/share/*` 由先注册的路由优先匹配。
- **接口契约**：`/api/chat` 为 `text/event-stream`，帧为 `{"type":"text"|"error"|"done", ...}`；`error` 帧的 `code` 只有 `auth_error` / `network_error` / `upstream_error` 三类。**本次不改动任何接口**。
- **测试现状**：全量 pytest 295 项通过；**没有任何用例读取 `web/` 下的文件**（用例中出现的 `index.html` 都是会话沙箱内的文件），因此前端重写不会影响后端测试。
- **运行环境**：开发机已有 Node v24.18.0 与 npm 11.16.0。部署侧为 Nginx（`proxy_buffering off`、`proxy_read_timeout 300s`、按来源 IP 限流）+ systemd 拉起 uvicorn（`--workers 1`，监听 `127.0.0.1:80`），服务器上**没有** Node。

## Goals / Non-Goals

**Goals:**

- 助手自身界面迁移到 **React + TypeScript + Ant Design**，用成熟组件库替换手写组件，用类型系统锁住接口与 SSE 帧契约。
- 界面信息架构改为**侧边栏主导的经典后台布局**，把历史会话、版本、分享、示例等功能从顶栏弹层移入导航，主区聚焦「对话 + 预览」。
- 视觉统一：品牌色、圆角、字号层级、间距由 `ConfigProvider` 的 `theme.token` 统一下发，不再散落字面量。
- 主题三态（自动 / 浅色 / 深色）语义与记忆行为保持不变，改为驱动 antd 的 `theme.algorithm`。
- 依赖本地化：`marked` / `DOMPurify` / `highlight.js` 随包构建，**彻底去掉 CDN**。
- 部署流程对服务器**零新增依赖**：`web/dist/` 随仓库提交，`git pull` + 重启即生效。

**Non-Goals:**

- 不改任何后端接口、SSE 帧协议、会话与沙箱落盘结构；不改版本 / 分享 / 预览 / 下载的既有语义。
- 不向**生成的应用**或示例模板引入任何外部框架；生成的产物仍是沙箱内自包含的 `index.html` + 样式 + 脚本；预览 `iframe` 的 `sandbox` 与票据路径不变。
- 不引入全局状态库（Redux / Zustand / MobX）与路由库（本次是单页应用，无 URL 路由需求）。
- 不做服务端渲染（SSR / SSG）；不做 PWA、离线缓存与国际化多语言（界面仍为中文）。
- 不引入前端单元测试框架（理由见决策 9）。
- 不重写示例模板与提示词；不改 `templates/examples/`。

## Decisions

### 1. 技术栈与构建链：Vite + React 18 + TypeScript + antd 5

- **做法**：`web/` 下新增 `package.json`、`tsconfig.json`、`vite.config.ts`、`index.html`（Vite 入口）与 `src/`；构建输出 `web/dist/`。React 18 + TypeScript，UI 用 antd 5（ESM，Vite 原生 tree-shaking，按需打包）。`vite.config.ts` 的 `base` 保持 `/`，开发态 `server.proxy` 把 `/api`、`/preview`、`/share` 代理到 `http://127.0.0.1:80`（**同源访问，避免跨域导致登录态 Cookie 不带上**）。
- **理由**：Vite 是当前 React 生态最轻的构建方案（无需额外配置即可支持 TS 与按需引入）；antd 5 自带 design token 与暗色算法，正好替换手写的令牌系统；TypeScript 能把 SSE 帧与接口响应定成类型，降低与后端漂移的风险——这正是当前 1400 行 `app.js` 最缺的东西。
- **备选**：Next.js（被排除：需要 Node 运行时做 SSR，与「纯静态托管、服务器无 Node」冲突）；CRA / webpack（被排除：配置重、已过时）；Svelte / Vue（被排除：需求明确指向 antd，而 antd 是 React 专用库）。

### 2. 构建产物提交进仓库，并在启动时校验存在性

- **做法**：`web/dist/` **提交进版本库**；`.gitignore` 只新增 `web/node_modules/`（不忽略 `dist`）。`app/main.py` 的 `WEB_DIR` 改为 `web/dist`，并在启动时校验 `web/dist/index.html` 存在——缺失则**启动失败**并给出中文提示（例如「前端构建产物缺失：请先在 `web/` 下执行 `npm install && npm run build`，或从版本库拉取最新的 `web/dist/`」）。
- **理由**：服务器上**没有 Node**，部署流程是 `git pull` + `systemctl restart`；提交产物能让部署保持零改动，符合既有部署样例。启动校验把「忘记构建就部署」从「页面白屏、原因不明」变成「启动即失败、原因明确」，与项目「配置缺失时启动失败并点名」的既有风格一致。
- **代价与约束**：仓库里会出现编译产物的 diff 噪音；**必须**在 README 写清「修改前端后要重新 `npm run build` 并提交 `web/dist/`，否则线上仍是旧界面」。启动校验只能确认产物存在，无法确认与源码一致，因此该约定靠文档与流程保证。

### 3. 目录结构（源码与产物分离）

```
web/
├── package.json / tsconfig.json / vite.config.ts / .gitignore
├── index.html                 # Vite 入口（内联主题预设脚本，避免首屏闪白）
├── src/
│   ├── main.tsx               # 挂载 React、ConfigProvider、主题与认证 Provider
│   ├── types.ts               # 接口响应与 SSE 帧的类型定义（与后端契约一对一）
│   ├── api/
│   │   ├── client.ts          # fetch 封装：同源凭据、JSON、401 集中处理
│   │   └── chat.ts            # /api/chat 的 SSE 流解析（ReadableStream）
│   ├── hooks/                 # useAuth / useTheme / useSessions / useChatStream / usePreview
│   ├── components/
│   │   ├── layout/            # AppShell（Layout + Sider + Header）、SiderNav
│   │   ├── chat/              # MessageList、MessageBubble、Composer、ProgressStatus
│   │   ├── markdown/          # MarkdownView（marked + DOMPurify + highlight.js）、CodeBlock 操作
│   │   ├── preview/           # PreviewPanel（iframe + 票据刷新）
│   │   └── dialogs/           # 版本、分享、示例、改密
│   └── theme/                 # antd token 与主题解析（三态 → algorithm）
└── dist/                      # 构建产物（随仓库提交，由 FastAPI 静态托管）
```

- **理由**：把「按职责分包」而非「按页面分包」，是因为本次只有一个主页面，复杂度来自各类交互（流式、预览、弹层）。`types.ts` 单独存在，是为了让 SSE 帧与接口结构的类型成为**单一事实来源**，与后端 `app/schemas.py`、`FrameBuilder` 一一对应。`markdown/` 独立成包，因为它是唯一需要 `dangerouslySetInnerHTML` 的地方，安全边界要显式。

### 4. 布局：antd `Layout`，侧边栏主导，窄屏折叠为 `Drawer`

- **做法**：`Layout` + `Sider`（可折叠）承载导航与功能入口；`Header` 保留品牌、会话 ID、主题切换与用户操作；`Content` 为「对话 + 预览」两栏——宽屏左右并排，窄屏上下堆叠（或切为 `Tabs`）。侧边栏分区：上为新建会话与导航（对话 / 历史会话 / 示例应用 / 版本 / 分享），下为用户区（当前用户、修改密码、退出）。窄屏时 `Sider` 隐藏，改用 `Drawer` 打开同一份导航。
- **理由**：功能入口已有 8 个以上，继续堆在顶栏会持续拥挤（上一轮已经出现过顶栏按钮过多的迹象），侧边栏是成熟后台产品的通用解法，也让「历史会话」这种需要常驻浏览的内容有了自然的落点。
- **保留的语义**：会话 ID 仍然**始终可见**（调试用，既有硬约束）；退出登录、修改密码、下载整个项目、主题切换均在侧边栏或用户菜单中可达，不因搬家而丢失。

### 5. 主题：沿用三态语义，驱动 antd `theme.algorithm`

- **做法**：保留 `auto` / `light` / `dark` 三态与 `localStorage` 键 `code-assistant.theme`。`auto` 时读取并监听 `matchMedia('(prefers-color-scheme: dark)')`，解析出实际主题后传入 `ConfigProvider theme={{ algorithm: dark ? darkAlgorithm : defaultAlgorithm, token }}`；`token` 集中定义品牌色、圆角、字号与间距。代码高亮保留浅色 / 深色两套样式并随主题切换。
- **首屏不闪白**：在 `web/index.html` 的 `<head>` 内联一段极短脚本，读取本机主题选择并提前在 `document.documentElement` 上打标，使首屏就按最终主题渲染。
- **理由**：主题语义已经过用户验收（自动跟随系统 + 手动切换 + 记忆），不因换栈而改变；用 `algorithm` 而不是自己覆盖 CSS，能保证 antd 全部组件（含浮层、滚动条、阴影）在暗色下协调一致。

### 6. 状态管理：hooks + 少量 Context，不引入状态库与路由库

- **做法**：认证态、主题、当前会话与预览刷新用 React Context；对话流用 `useChatStream` hook 封装（`fetch` + `ReadableStream` 解析 SSE 帧、`AbortController` 中断、500ms 进度定时器、错误帧收集与重试）。不引入 Redux / Zustand，不引入 React Router。
- **理由**：状态总量不大且层级浅，Context + hook 足够；引入状态库会让这类「一次性交互状态」变复杂。没有 URL 路由需求（单页、无分享给前端的深链接），路由库属于纯增负担。

### 7. 内容渲染与代码块操作：`dangerouslySetInnerHTML` 收口在一处

- **做法**：`MarkdownView` 是唯一使用 `dangerouslySetInnerHTML` 的组件：`marked` 渲染 → `DOMPurify` 清洗 → 注入。代码块的「复制 / 另存为」按钮**不**嵌进 HTML 字符串，而是渲染后用 `ref` 遍历 `pre > code` 节点，为每个代码块挂一个轻量操作条（携带语言与文本），从而保持「清洗后的 HTML 只含内容、不含交互逻辑」。`highlight.js` 在注入后对节点执行 `highlightElement`；浅色 / 深色两份主题样式随界面主题切换。
- **理由**：把唯一的 XSS 风险面收在一个组件里，便于审查；把按钮放在 React 侧而不是 Markdown 生成的 HTML 里，避免「用户内容里能伪造操作按钮」这类风险，也避免把 React 组件塞进 `innerHTML`。
- **降级**：`marked` / `highlight.js` 处理失败时退化为纯文本展示，**不白屏**（沿用既有要求）。

### 8. 401 与错误呈现集中到 API 封装层

- **做法**：`api/client.ts` 统一处理响应：401 → 清理登录态并切回认证界面 + antd 全局提示「登录态已失效，请重新登录」；网络异常与 5xx → 抛出携带中文说明的错误，由调用方用 `message.error` / `Alert` 呈现。SSE 的 `error` 帧仍按三类 `code` 展示中文说明与「重试」按钮。
- **理由**：既有实现已把 401 集中处理（对话、会话列表、历史、下载、预览、版本、分享），迁移时保持单一收口点，避免散落到各组件里。

### 9. 不引入前端单元测试框架

- **做法**：不新增 Vitest / Jest / Testing Library；前端验收以**真实浏览器逐项实测**为准（登录、流式、进度、中断、重试、示例即预览、版本、分享、下载、主题、窄屏），后端继续跑全量 pytest（295 项，不受影响）。
- **理由**：项目目前只维护一套 pytest；为一次界面迁移再引入一套 JS 测试基建，收益主要是组件快照，而本次风险集中在「与后端契约一致性」与「交互是否可用」——前者靠 TypeScript 类型与既有后端测试守住，后者只能靠真实浏览器验证。若后续前端逻辑继续膨胀（例如出现本地缓存、复杂表单），再单独立项引入。

### 10. 生成的应用与示例模板不受任何影响

- **做法**：提示词中的「不依赖外部 CSS 框架、自包含」约定保持不变；`templates/examples/` 不改；预览 `iframe` 的 `sandbox` 属性、票据路径与刷新流程照旧迁移。
- **理由**：生成的应用要能在任何环境打开（含下载后本地双击 `index.html`），一旦引用外部框架就会破坏这一点；助手界面用 antd 与生成的应用自包含，是两条互不干扰的轨道。

## Risks / Trade-offs

- [构建产物与源码可能不同步] → 启动校验只能保证产物存在；缓解方式是在 README 与 `docs/project-overview.md` 显著位置写明「改前端必须重新构建并提交 `web/dist/`」，并在 tasks 中把「构建后提交」作为交付步骤。
- [产物体积增大] → React + antd 的 gzip 产物约百余 KB，远小于此前「每轮对话都走 CDN 拉三个库」的代价；通过 Vite 按需引入与不引入多余依赖控制体积，并去掉 `moment` 类重依赖（antd 5 用轻量日期库）。
- [仓库 diff 噪音] → `web/dist/` 为压缩产物，每次构建都会产生大块 diff；这是用户明确选择的取舍（部署零改动优先）。若后续仓储成本变高，可改为「部署时在服务器构建」，届时只需改回 `.gitignore` 与部署步骤。
- [重写期间的回归风险] → 1400 行 `app.js` 的交互需逐项迁移，遗漏风险高；缓解方式是按 tasks.md 分模块迁移，每迁完一块即用浏览器实测该块，最后做一次全链路验收。
- [首屏闪白] → 主题与 dark 算法在 React 挂载后才生效；缓解方式是 `index.html` 内联预设脚本，并在 tasks 中把「首屏主题正确」列为验收项。
- [antd 版本与 `Splitter` 等新组件可用性] → 两栏布局以 CSS 实现为主，不依赖特定新组件版本；若某组件在锁定版本中不可用，改用等价组合（如 `Card` + `Grid`），不因此升级到未经验证的大版本。

## Migration Plan

1. **搭骨架**：在 `web/` 建立 `package.json` / `tsconfig.json` / `vite.config.ts` / `index.html` 与 `src/` 目录骨架，跑通「Vite 构建出可打开的空白 React 页面」。
2. **契约层**：定义 `types.ts` 与 `api/client.ts`（含 401 集中处理）、`api/chat.ts`（SSE 解析），保证帧与接口类型与后端一一对应。
3. **认证**：迁移登录 / 注册 / 改密与认证门控。
4. **主界面骨架**：`AppShell`（`Layout` + `Sider` + `Header`）与主题（含首屏预设）。
5. **对话与流式**：消息列表、Markdown 渲染与代码块操作、输入区、进度、中断、重试。
6. **预览与弹层**：预览面板与票据刷新、版本、分享、示例、下载。
7. **切换托管**：`app/main.py` 指向 `web/dist` 并加启动校验；确认 `/api`、`/preview`、`/share` 路由优先级不受影响。
8. **清理与交付**：删除旧 `web/index.html` / `web/styles.css` / `web/app.js`；构建并提交 `web/dist/`。
9. **文档与验收**：更新 README 与项目概览；跑全量 pytest；用真实浏览器做全链路验收。