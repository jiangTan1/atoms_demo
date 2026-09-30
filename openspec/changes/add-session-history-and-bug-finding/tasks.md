# Tasks

## 1. 变更文档与基线确认

- [x] 1.1 按 proposal.md / design.md 落地本变更的 specs 增量（`session-history`、`code-assistant-agent`），验证方式是执行 `openspec validate "add-session-history-and-bug-finding" --strict` 通过
- [x] 1.2 清理探针残留：删除 `data/sessions.db` 中由验证脚本写入的 `probe-user` 会话，验证方式是重新启动服务后历史会话列表不出现探针数据

## 2. 会话落盘与配置

- [x] 2.1 把 `app/config.py` 中 `SESSION_BACKEND` 的默认取值由 `memory` 改为 `sqlite`，并同步更新 `.env.example` 的说明，验证方式是清空 `SESSION_BACKEND` 后启动，运行日志与 `data/sessions.db` 均显示使用 SQLite 后端
- [x] 2.2 同步修改本地 `.env` 的 `SESSION_BACKEND=sqlite`，验证方式是启动后完成一次提问，`data/sessions.db` 中出现可查询的会话记录
- [x] 2.3 在 `app/services/chat.py` 中新增事件→消息还原函数（`author='user'` 为用户消息，其余为助手消息，跳过 partial/空文本/纯错误事件），验证方式是 `tests/test_chat_frames.py` 新增用例覆盖「多轮问答还原」「跳过中间态与错误事件」并全部通过

## 3. 历史会话接口

- [x] 3.1 在 `app/schemas.py` 中补充会话摘要与历史消息的响应模型（会话标识、标题、最近更新时间、消息数；消息的角色与文本），验证方式是序列化后的 JSON 字段与 design.md 决策 3 一致
- [x] 3.2 在 `app/api/sessions.py` 中实现 `GET /api/sessions`：按最近更新时间倒序返回最近 50 条会话摘要，标题取首条用户消息摘要、无消息时标记为空会话，验证方式是调用接口能返回多条会话且顺序为最近更新优先
- [x] 3.3 在 `app/api/sessions.py` 中实现 `GET /api/sessions/{session_id}/messages`：返回按时间顺序还原的历史消息，会话不存在时返回 404，验证方式是调用接口能按顺序取回用户与助手消息
- [x] 3.4 确认新增路由不影响既有 `POST /api/sessions`、`GET /api/sessions/{session_id}` 与 `POST /api/chat` 的请求响应契约，验证方式是逐个调用四个端点均返回预期结构

## 4. 前端历史会话

- [x] 4.1 在 `web/index.html` 与 `web/styles.css` 中新增「历史会话」面板（列表容器、条目样式、窄屏不溢出），验证方式是浏览器中面板元素齐全且布局正常
- [x] 4.2 在 `web/app.js` 中用 `localStorage` 记住 `session_id`：每轮对话收到 `done` 帧后写入，页面加载时读取并载入对应历史消息，验证方式是完成提问后刷新页面，历史对话仍完整显示
- [x] 4.3 在 `web/app.js` 中实现历史会话列表的拉取与渲染，点击条目即切换会话并重渲染消息区，验证方式是切换两个不同会话时消息区内容随之改变
- [x] 4.4 处理失效会话：载入历史时若返回 404 或请求失败，清除本地记录并进入可直接提问的新会话状态且给出轻量提示，验证方式是在服务端清除该会话后刷新页面，页面不报错且可继续提问
- [x] 4.5 让新建会话与历史列表联动：新建后清空消息区、刷新列表并高亮当前会话，验证方式是连续新建两次后列表出现两个可辨识条目

## 5. 提示词：第四类任务

- [x] 5.1 在 `prompts/system.md` 中把「只处理三类任务」更新为四类，并新增「任务四：缺陷排查与优化点识别」章节，约束输出结构为 问题清单（严重程度/位置/触发条件/后果）→ 修复后完整代码 → 改动说明，验证方式是逐条比对 `specs/code-assistant-agent/spec.md` 中「缺陷排查与优化点识别」的每个 Scenario 都能在提示词中找到对应约束
- [x] 5.2 在提示词中补充「无实质问题时如实说明、最多给少量可选优化点、不得凑数」的约束，验证方式是提交一段无明显缺陷的代码，助手如实说明而非罗列伪问题

## 6. 测试与端到端验证

- [x] 6.1 运行 `py -3.12 -m pytest` 确认全部单元测试通过（含本次新增用例）
- [x] 6.2 端到端验收（历史会话）：完成两轮提问 → 刷新页面确认历史完整恢复 → 重启服务后确认会话仍在列表中且可切换，逐条记录 `specs/session-history/spec.md` 的 Scenario 通过情况
- [x] 6.3 端到端验收（缺陷排查）：提交一段含典型缺陷的代码（如并发/空值/资源未释放）确认输出分级问题清单与修复后完整代码；再提交一段无缺陷代码确认不编造问题
- [x] 6.4 更新 `README.md`：说明会话默认落盘、`data/sessions.db` 的作用与清理方式、历史会话面板用法、第四类任务的提问方式，并注明由内存切换到 SQLite 后旧会话不迁移