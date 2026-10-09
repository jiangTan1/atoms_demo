# Proposal

## Why

助手自身的前端此前刻意选择了「零构建 + 自建设计令牌」：`web/` 下三个文件（`index.html` / `styles.css` / `app.js`），手写 CSS 变量统一间距、圆角、配色与字体层级，暗色靠 `prefers-color-scheme` 与 `html[data-theme]` 两层覆盖。这套做法在「不引入依赖」的前提下已经把观感拉到可用水平，但天花板很明显：

- **组件要手写**。弹层、下拉、表格、提示、抽屉、日期与数值输入等都得自己实现，缺少统一的交互细节（焦点管理、键盘可达、动效、无障碍），功能一多就开始各写一套。
- **样式靠约定维持**。设计令牌只是变量，没有约束力；新增界面很容易绕过令牌写字面量，长期一致性靠人盯。
- **业务逻辑全在一个文件里**。`web/app.js` 已经超过千行，认证、会话、SSE 流、进度、中断、重试、版本、分享、示例、主题全部挤在模块级函数与全局状态中，改动一处要通读全文，且没有类型约束——SSE 帧结构与接口字段一旦与后端漂移，只能等运行时报错。
- **依赖仍走 CDN**。`marked` / `DOMPurify` / `highlight.js` 从 cdnjs 引入，离线或被拦截时只能降级为纯文本。

本次变更把助手自身界面**整体迁移到 React + TypeScript + Ant Design（Vite 构建）**，用成熟组件库与类型系统替换手写组件与约定式样式；界面信息架构改为**侧边栏主导的经典后台布局**。生成的应用仍保持自包含、不引用任何外部 CSS 框架。

## What Changes

- **技术栈整体替换**：新增 `web/package.json`、`web/vite.config.ts`、`web/tsconfig.json` 与 `web/src/`（React 18 + TypeScript + antd 5），构建产物输出到 `web/dist/`；原 `web/index.html` / `web/styles.css` / `web/app.js` 删除，功能全部在 `web/src/` 中重写。
- **界面信息架构改为侧边栏主导**：`antd` `Layout`——左侧 `Sider`（品牌区 + 功能导航：对话 / 历史会话 / 示例应用 / 版本 / 分享；底部用户区）承载主功能入口，顶部 `Header` 保留会话 ID、主题切换与用户操作，主内容区为「对话 + 应用预览」两栏；窄屏时 `Sider` 折叠并在 `Drawer` 中展开。
- **组件与视觉统一到 antd**：按钮、输入、弹层（`Modal` / `Drawer`）、列表、空状态、提示（`message` / `notification`）、加载态、标签页、下拉菜单、表单校验等改用 antd 组件；视觉通过 `ConfigProvider` 的 `theme.token` 集中设定品牌色、圆角、字号层级与间距，不再手写组件样式。
- **主题与暗色**：沿用现有三态语义（自动 / 浅色 / 深色），用 antd `theme.algorithm`（`defaultAlgorithm` / `darkAlgorithm`）实现，选择记在本机；跟随系统时监听系统偏好变化。
- **依赖本地化**：`marked`、`DOMPurify`、`highlight.js` 改为 npm 依赖随包构建，**去掉全部 CDN 引用**；代码高亮保留浅色 / 深色两套主题并随界面主题切换。
- **既有交互全部保留**：登录 / 注册 / 改密、会话 ID 展示、会话与历史消息、SSE 流式渲染与打字机、执行进度、主动中断、失败重试、401 集中处理、应用预览与刷新、版本列表与回滚、分享链接生成、整项目下载、示例应用选择即预览、代码块「复制 / 另存为」按钮——语义与入口不变，仅实现与呈现方式改变。
- **构建产物交付**：`web/dist/` **提交进版本库**，服务器无需安装 Node，部署流程（`git pull` + 重启 systemd）保持不变；服务启动时若构建产物缺失，**启动失败并明确提示先执行前端构建**。
- **生成的应用不受影响**：不向生成的应用或示例模板引入任何外部框架，仍为沙箱内自包含的 `index.html` + 样式 + 脚本。

## Capabilities

### New Capabilities

- `frontend-build-pipeline`：前端源码组织与构建（Vite + TypeScript）、构建产物的交付方式与静态托管、开发态代理与生产态部署约定，以及构建产物缺失时的启动行为。

### Modified Capabilities

- `web-ui-design-system`：**推翻「保持零构建」**（原要求显式禁止引入前端框架与组件库），改为基于 antd 组件与 `ConfigProvider` 令牌的设计体系；保留并重述暗色模式、响应式表现与「不白屏」要求。设计力量从「自己实现」转为「配置与约束」。
- `web-chat`：界面信息架构由「顶栏 + 弹层」改为**侧边栏主导的后台布局**；对话、预览、进度、中断、重试、版本、分享、示例等既有交互语义不变，仅承载方式与呈现改变。

## Impact

- **代码**：新增 `web/package.json`、`web/vite.config.ts`、`web/tsconfig.json`、`web/index.html`（Vite 入口）、`web/src/**`（组件、hooks、API 封装、类型定义）；删除 `web/styles.css`、`web/app.js` 与旧 `web/index.html`；新增 `web/dist/**`（构建产物，随仓库提交）；`app/main.py` 的 `WEB_DIR` 指向 `web/dist` 并增加产物存在性校验；`.gitignore` 增加 `web/node_modules/`（`dist` **不**忽略）。
- **接口**：**无任何后端接口变化**。既有 `/api/*`、`/preview/{会话}/{票据}/…`、`/share/*` 的路径、请求与响应形态（含 SSE 帧协议 `text` / `error` / `done`）保持不变。
- **数据**：无落盘格式变化；`data/sessions.db`、`data/workspace/`、`data/versions/` 语义不变。
- **测试**：既有 295 项 pytest **不受影响**（无用例依赖前端文件），预期全量通过；不引入前端单元测试框架，前端验收以真实浏览器逐项实测为准。
- **部署**：服务器仍只需 Python 环境，Nginx 与 systemd 配置不变；开发机新增 Node 依赖（Node 24 / npm 11 已具备）。文档需说明「修改前端后必须重新构建并提交 `web/dist/`」。
- **文档**：`README.md`（技术栈、目录结构、开发与部署流程、前端构建步骤、CDN 说明改写）与 `docs/project-overview.md`（分层表、完成度表、已知限制中的 CDN 与零构建相关条目）需同步更新。
- **兼容性**：后端、沙箱、版本、分享、预览与下载行为完全兼容；界面视觉与布局有显著变化，但功能入口与语义一一对应，无功能删除。