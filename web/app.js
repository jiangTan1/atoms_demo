// 前端逻辑：对话生成网页应用、应用预览、版本回滚与分享，以及 SSE 消费与会话恢复

const LANG_LABELS = {
  java: 'Java',
  python: 'Python',
  csharp: 'C#',
  cpp: 'C++',
  html: 'HTML',
  javascript: 'JavaScript',
};
const MAX_LANG_LABEL_LEN = 12;

// 「另存为」按语言决定扩展名，未标注语言时统一存为 .txt（见 design.md 决策 7）
const LANG_EXTENSIONS = {
  java: 'java',
  python: 'py',
  csharp: 'cs',
  cpp: 'cpp',
  html: 'html',
  javascript: 'js',
};

// 记住当前会话，刷新页面后据此自动恢复历史
const SESSION_STORAGE_KEY = 'code-assistant.session_id';
const SESSION_ID_PLACEHOLDER = '新会话（尚未创建）';

// 预览区占位文案：无会话、无入口文件、预览失败都从这里起步（见 tasks.md 4.3）
const PREVIEW_EMPTY_TEXT =
  '还没有可预览的应用。在左侧描述你想要的网页应用（例如「做一个俄罗斯方块小游戏」），生成后这里会显示它，并可以直接操作。';

const els = {
  authApp: document.getElementById('auth-app'),
  chatApp: document.getElementById('chat-app'),
  authForm: document.getElementById('auth-form'),
  authModeLogin: document.getElementById('auth-mode-login'),
  authModeRegister: document.getElementById('auth-mode-register'),
  authModePassword: document.getElementById('auth-mode-password'),
  authUsername: document.getElementById('auth-username'),
  authPassword: document.getElementById('auth-password'),
  authSubmit: document.getElementById('auth-submit'),
  authCancel: document.getElementById('auth-cancel'),
  authTip: document.getElementById('auth-tip'),
  currentUser: document.getElementById('current-user'),
  changePassword: document.getElementById('change-password'),
  logout: document.getElementById('logout'),
  passwordModal: document.getElementById('password-modal'),
  passwordForm: document.getElementById('password-form'),
  passwordModalUser: document.getElementById('password-modal-user'),
  passwordOld: document.getElementById('password-old'),
  passwordNew: document.getElementById('password-new'),
  passwordSubmit: document.getElementById('password-submit'),
  passwordCancel: document.getElementById('password-cancel'),
  passwordTip: document.getElementById('password-tip'),
  messages: document.getElementById('messages'),
  input: document.getElementById('input'),
  send: document.getElementById('send'),
  interrupt: document.getElementById('interrupt'),
  themeToggle: document.getElementById('theme-toggle'),
  newSession: document.getElementById('new-session'),
  downloadProject: document.getElementById('download-project'),
  historyToggle: document.getElementById('history-toggle'),
  historyPanel: document.getElementById('history-panel'),
  historyList: document.getElementById('history-list'),
  historyRefresh: document.getElementById('history-refresh'),
  status: document.getElementById('status'),
  sessionId: document.getElementById('session-id'),
  previewFrame: document.getElementById('preview-frame'),
  previewPlaceholder: document.getElementById('preview-placeholder'),
  previewState: document.getElementById('preview-state'),
  previewRefresh: document.getElementById('preview-refresh'),
  versionsOpen: document.getElementById('versions-open'),
  versionsModal: document.getElementById('versions-modal'),
  versionsList: document.getElementById('versions-list'),
  versionsClose: document.getElementById('versions-close'),
  versionsTip: document.getElementById('versions-tip'),
  shareOpen: document.getElementById('share-open'),
  shareModal: document.getElementById('share-modal'),
  shareVersion: document.getElementById('share-version'),
  shareCreate: document.getElementById('share-create'),
  shareList: document.getElementById('share-list'),
  shareClose: document.getElementById('share-close'),
  shareTip: document.getElementById('share-tip'),
  examplesOpen: document.getElementById('examples-open'),
  examplesModal: document.getElementById('examples-modal'),
  examplesList: document.getElementById('examples-list'),
  examplesClose: document.getElementById('examples-close'),
  examplesTip: document.getElementById('examples-tip'),
  hljsLight: document.getElementById('hljs-light'),
  hljsDark: document.getElementById('hljs-dark'),
};

let sessionId = null;
let streaming = false;

// 本轮生成的取消控制器与「是否由使用者主动中断」标记（见 design.md 决策 2）
let activeController = null;
let interrupted = false;

// 发送过的最后一条用户消息，供出错后的「重试」原样重发
let lastUserMessage = '';

// 执行中的进度反馈：本轮已接收文本与开始时间，定时器每 500ms 刷新（见 design.md 决策 4）
let streamRaw = '';
let turnStartedAt = 0;
let progressTimer = null;

// 认证界面当前表单：login / register（改密已收进已登录界面，见 design.md 决策 11）
let authMode = 'login';

// 当前登录用户名，改密表单据此展示归属，不需要使用者重填
let currentUsername = '';

// CDN 未加载时下方逻辑仍需可用，这里先做存在性判断
if (window.marked) {
  marked.setOptions({ gfm: true, breaks: true });
}

function setStatus(text) {
  els.status.textContent = text || '';
}

/** 顶栏展示当前会话 ID，方便排查问题；无会话时显示占位文案。 */
function renderSessionId() {
  els.sessionId.textContent = sessionId || SESSION_ID_PLACEHOLDER;
  els.sessionId.title = sessionId ? `当前会话 ID：${sessionId}` : '当前还没有会话 ID';
}

function removeEmptyHint() {
  const hint = document.getElementById('empty-hint');
  if (hint) hint.remove();
}

function restoreEmptyHint() {
  const hint = document.createElement('div');
  hint.className = 'empty';
  hint.id = 'empty-hint';
  hint.innerHTML =
    '<p>描述你想要的网页应用，智能体会生成可运行的文件并在这里预览。</p>' +
    '<p class="hint">示例：做一个俄罗斯方块小游戏；做一个能算账的记账页面；给这个应用加一个计分板。</p>' +
    '<p class="hint">想立刻看到成品？点顶栏的「示例应用」，选一个内置小游戏或小工具即可。</p>';
  els.messages.appendChild(hint);
}

function clearMessages() {
  els.messages.innerHTML = '';
  restoreEmptyHint();
}

function scrollToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

// --- 消息渲染 ---

function addMessage(role, text) {
  removeEmptyHint();
  const wrap = document.createElement('div');
  wrap.className = `message ${role}`;

  const label = document.createElement('span');
  label.className = 'role';
  label.textContent = role === 'user' ? '你' : '助手';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  const content = document.createElement('div');
  content.className = 'content';
  bubble.appendChild(content);

  wrap.append(label, bubble);
  els.messages.appendChild(wrap);

  if (role === 'user') {
    content.textContent = text;
  }
  scrollToBottom();
  return content;
}

/** 在回复气泡下展示错误提示；onRetry 非空时附上「重试」按钮。 */
function showError(contentEl, message, onRetry) {
  const tip = document.createElement('div');
  tip.className = 'error-tip';

  const text = document.createElement('span');
  text.className = 'error-text';
  text.textContent = message;
  tip.appendChild(text);

  if (onRetry) {
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'ghost retry-btn';
    retry.textContent = '重试';
    retry.addEventListener('click', () => {
      const wrap = contentEl.closest('.message');
      tip.remove();
      if (wrap) wrap.remove();
      onRetry();
    });
    tip.appendChild(retry);
  }

  contentEl.parentElement.appendChild(tip);
  scrollToBottom();
}

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function renderMarkdown(target, markdown) {
  const source = markdown || '';
  // CDN 库未加载时退化为纯文本展示，页面与对话依然可用
  const html = window.marked
    ? marked.parse(source)
    : `<pre class="plain-text">${escapeHtml(source)}</pre>`;
  target.innerHTML = window.DOMPurify
    ? DOMPurify.sanitize(html, { USE_PROFILES: { html: true } })
    : html;
  enhanceCodeBlocks(target);
  scrollToBottom();
}

function detectLanguage(codeEl) {
  const match = /language-([\w+#-]+)/i.exec(codeEl.className || '');
  const raw = match ? match[1].toLowerCase() : '';
  if (raw === 'c#' || raw === 'cs') return 'csharp';
  if (raw === 'c++' || raw === 'cc' || raw === 'cxx') return 'cpp';
  if (raw === 'js') return 'javascript';
  return raw.slice(0, MAX_LANG_LABEL_LEN);
}

/** 同一次渲染内出现同名文件时追加序号，避免重复下载覆盖。 */
function uniqueFileName(base, ext, used) {
  const count = (used.get(ext) || 0) + 1;
  used.set(ext, count);
  return count === 1 ? `${base}.${ext}` : `${base}-${count}.${ext}`;
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function saveAsFile(text, filename) {
  saveBlob(new Blob([text], { type: 'text/plain;charset=utf-8' }), filename);
}

function enhanceCodeBlocks(root) {
  const usedNames = new Map();

  root.querySelectorAll('pre > code').forEach((codeEl) => {
    if (codeEl.closest('.code-block')) return;

    const language = detectLanguage(codeEl);
    const source = codeEl.textContent;

    if (window.hljs) {
      codeEl.classList.add('hljs');
      // 未标注语言时保持纯文本展示，不做自动探测，避免流式过程中的额外开销
      if (language && hljs.getLanguage(language)) {
        codeEl.innerHTML = hljs.highlight(source, { language }).value;
      }
    }

    const block = document.createElement('div');
    block.className = 'code-block';

    const head = document.createElement('div');
    head.className = 'code-head';

    const label = document.createElement('span');
    label.className = 'code-lang';
    label.textContent = LANG_LABELS[language] || language || '纯文本';

    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'code-copy';
    copyBtn.textContent = '复制';
    copyBtn.addEventListener('click', async () => {
      const ok = await copyText(source);
      copyBtn.textContent = ok ? '已复制' : '复制失败';
      setTimeout(() => {
        copyBtn.textContent = '复制';
      }, 1500);
    });

    const fileName = uniqueFileName('snippet', LANG_EXTENSIONS[language] || 'txt', usedNames);
    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'code-copy';
    saveBtn.textContent = '另存为';
    saveBtn.title = `保存为 ${fileName}`;
    saveBtn.addEventListener('click', () => {
      saveAsFile(source, fileName);
      saveBtn.textContent = '已保存';
      setTimeout(() => {
        saveBtn.textContent = '另存为';
      }, 1500);
    });

    const tools = document.createElement('span');
    tools.className = 'code-tools';
    tools.append(copyBtn, saveBtn);

    head.append(label, tools);

    const pre = codeEl.parentElement;
    pre.replaceWith(block);
    block.append(head, pre);
  });
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      /* 回落到 execCommand */
    }
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  } catch (err) {
    return false;
  }
}

// --- SSE 消费 ---

function parseFrame(chunk) {
  const payload = chunk
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
    .join('');
  if (!payload) return null;
  try {
    return JSON.parse(payload);
  } catch (err) {
    return null;
  }
}

async function describeHttpError(response) {
  let detail = '';
  try {
    const body = await response.json();
    detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
  } catch (err) {
    detail = await response.text().catch(() => '');
  }
  return `请求失败（HTTP ${response.status}）${detail ? '：' + detail : ''}`;
}

// --- 执行进度与中断（见 design.md 决策 1、2、4）---

function countLines(text) {
  return text ? text.split('\n').length : 0;
}

function stopProgress() {
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
}

/** 状态区显示「正在生成第 N 行 · 已用 M 秒」，让使用者知道后台在推进。 */
function renderProgress() {
  const seconds = Math.floor((Date.now() - turnStartedAt) / 1000);
  const lines = countLines(streamRaw);
  setStatus(
    lines
      ? `正在生成第 ${lines} 行 · 已用 ${seconds} 秒`
      : `正在等待模型响应 · 已用 ${seconds} 秒`
  );
}

function startProgress() {
  turnStartedAt = Date.now();
  streamRaw = '';
  stopProgress();
  renderProgress();
  progressTimer = setInterval(renderProgress, 500);
}

/** 使用者主动取消长任务：断开请求，服务端随之取消本轮生成（见 decision 2）。 */
function interrupt() {
  if (!streaming || !activeController) return;
  interrupted = true;
  activeController.abort();
  setStatus('正在中断…');
}

/** 表单入口：把输入框内容作为新的一轮发出。 */
function send() {
  const text = els.input.value.trim();
  if (!text || streaming) return;
  els.input.value = '';
  addMessage('user', text);
  lastUserMessage = text;
  runTurn(text);
}

/**
 * 驱动一轮对话：消费 SSE 帧、给出进度、支持中断与重试。
 * text 为本轮发给服务端的内容（重试时原样重发）。
 */
async function runTurn(text) {
  if (streaming) return;
  const contentEl = addMessage('assistant', '');

  streaming = true;
  interrupted = false;
  els.send.disabled = true;
  els.interrupt.hidden = false;
  startProgress();

  const controller = new AbortController();
  activeController = controller;

  let raw = '';
  streamRaw = '';
  let errorMessage = '';
  let renderTimer = null;

  const renderNow = () => {
    if (renderTimer) {
      clearTimeout(renderTimer);
      renderTimer = null;
    }
    renderMarkdown(contentEl, raw);
  };
  const scheduleRender = () => {
    if (renderTimer) return;
    renderTimer = setTimeout(() => {
      renderTimer = null;
      renderMarkdown(contentEl, raw);
    }, 100);
  };
  // 重试：把同一轮内容原样重发（失败的气泡与提示由 showError 负责移除）
  const retry = () => runTurn(text);

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId }),
      signal: controller.signal,
    });

    if (response.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!response.ok || !response.body) {
      throw new Error(await describeHttpError(response));
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const frame = parseFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');
        if (!frame) continue;

        if (frame.type === 'text') {
          raw = frame.partial ? raw + frame.data : frame.data;
          streamRaw = raw;
          scheduleRender();
        } else if (frame.type === 'error') {
          // 任何错误帧（超时 / 限流 / 上游报错）都在收尾时给出「重试」按钮
          errorMessage = frame.data.message || '服务端返回错误';
        } else if (frame.type === 'done') {
          if (frame.data && frame.data.session_id) sessionId = frame.data.session_id;
        }
      }
    }
    // 响应已读完，之后的收尾动作不再受「中断」影响
    activeController = null;

    renderNow();
    if (errorMessage) {
      showError(contentEl, errorMessage, retry);
    } else if (!raw) {
      showError(contentEl, '本轮没有收到任何内容，请重试。', retry);
    }
    renderSessionId();
    if (sessionId) {
      rememberSession(sessionId);
      await refreshHistoryList();
    }
    // 一轮对话可能改动了沙箱，收尾后刷新预览让使用者立刻看到结果
    await refreshPreview();
  } catch (err) {
    renderNow();
    if (interrupted) {
      showError(
        contentEl,
        '已中断本轮生成。已写入沙箱的部分内容仍保留，可重新发送；若这是新会话，可在「历史会话」中找到它继续补齐。'
      );
      if (sessionId) await refreshPreview();
    } else {
      showError(contentEl, `连接中断或服务端异常：${err.message}`, retry);
    }
  } finally {
    stopProgress();
    activeController = null;
    streaming = false;
    els.send.disabled = false;
    els.interrupt.hidden = true;
    // 中断时保留说明性状态，其余情况清空进度
    setStatus(interrupted ? '本轮未完成，已写入沙箱的部分内容仍保留。' : '');
    els.input.focus();
  }
}

// --- 会话与语言 ---

function readStoredSession() {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY) || null;
  } catch (err) {
    return null;
  }
}

function rememberSession(id) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, id);
  } catch (err) {
    /* 隐私模式下 localStorage 不可用，忽略即可，不影响对话 */
  }
}

function forgetStoredSession() {
  try {
    localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch (err) {
    /* 同上 */
  }
}

// 新建会话不预先落库：首次提问时由服务端创建，避免历史列表里堆出空会话
function startNewSession() {
  clearMessages();
  sessionId = null;
  forgetStoredSession();
  els.input.value = '';
  setStatus('已新建会话');
  renderSessionId();
  highlightActiveSession();
  refreshPreview();
  els.input.focus();
}

// --- 项目打包下载 ---

/** 取服务端给出的下载文件名，取不到时用会话 ID 兜底。 */
function filenameFrom(response) {
  const header = response.headers.get('content-disposition') || '';
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match ? match[1] : `workspace-${sessionId.slice(0, 8)}.zip`;
}

/** 把当前会话沙箱内生成的全部文件打包下载（保留目录结构）。 */
async function downloadProject() {
  if (streaming) {
    setStatus('正在生成回复，请稍候再下载');
    return;
  }
  if (!sessionId) {
    setStatus('还没有会话与生成的文件，先让助手生成一个项目再下载');
    return;
  }

  els.downloadProject.disabled = true;
  setStatus('正在打包…');
  try {
    const response = await fetch(
      `/api/workspace/download?session_id=${encodeURIComponent(sessionId)}`
    );
    if (response.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!response.ok) {
      setStatus(await describeHttpError(response));
      return;
    }
    saveBlob(await response.blob(), filenameFrom(response));
    setStatus('已下载当前会话生成的全部文件');
  } catch (err) {
    setStatus(`下载失败：${err.message}`);
  } finally {
    els.downloadProject.disabled = false;
  }
}

function renderHistory(messages) {
  els.messages.innerHTML = '';
  if (!messages.length) {
    restoreEmptyHint();
    return;
  }
  messages.forEach((message) => {
    const contentEl = addMessage(message.role, message.text);
    if (message.role === 'assistant') {
      renderMarkdown(contentEl, message.text);
    }
  });
}

/** 载入历史消息：ok / missing（会话已不存在）/ unauthorized / error。 */
async function loadHistory(id) {
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(id)}/messages`);
    if (response.status === 401) {
      handleUnauthorized();
      return 'unauthorized';
    }
    if (response.status === 404) return 'missing';
    if (!response.ok) return 'error';
    const payload = await response.json();
    renderHistory(payload.messages || []);
    return 'ok';
  } catch (err) {
    return 'error';
  }
}

function formatTime(epochSeconds) {
  if (!epochSeconds) return '';
  const date = new Date(epochSeconds * 1000);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
}

function highlightActiveSession() {
  els.historyList.querySelectorAll('.history-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.sessionId === sessionId);
  });
}

function renderHistoryList(sessions) {
  els.historyList.innerHTML = '';
  if (!sessions.length) {
    const empty = document.createElement('p');
    empty.className = 'history-empty';
    empty.textContent = '暂无历史会话';
    els.historyList.appendChild(empty);
    return;
  }

  sessions.forEach((item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-item';
    button.dataset.sessionId = item.session_id;

    const title = document.createElement('span');
    title.className = 'history-title';
    title.textContent = item.title || '（空会话）';

    const meta = document.createElement('span');
    meta.className = 'history-meta';
    const time = formatTime(item.updated_at);
    meta.textContent = time
      ? `${time} · ${item.message_count} 条消息`
      : `${item.message_count} 条消息`;

    button.append(title, meta);
    button.addEventListener('click', () => switchSession(item.session_id));
    els.historyList.appendChild(button);
  });

  highlightActiveSession();
}

async function refreshHistoryList() {
  try {
    const response = await fetch('/api/sessions');
    if (response.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!response.ok) return;
    const payload = await response.json();
    renderHistoryList(payload.sessions || []);
  } catch (err) {
    /* 列表拉取失败不影响对话本身 */
  }
}

async function switchSession(id) {
  if (streaming) {
    setStatus('正在生成回复，请稍候再切换会话');
    return;
  }
  if (id !== sessionId) {
    const result = await loadHistory(id);
    if (result === 'ok') {
      sessionId = id;
      rememberSession(id);
      setStatus('已切换到历史会话');
    } else if (result === 'missing') {
      sessionId = null;
      forgetStoredSession();
      clearMessages();
      setStatus('该会话已不存在，已切到新会话');
    } else if (result === 'unauthorized') {
      return;
    } else {
      setStatus('历史会话载入失败，请稍后重试');
      return;
    }
    renderSessionId();
    // 预览跟随当前会话切换（见 tasks.md 4.3）
    await refreshPreview();
  }
  toggleHistory(false);
  await refreshHistoryList();
}

function toggleHistory(force) {
  const open = typeof force === 'boolean' ? force : els.historyPanel.hidden;
  els.historyPanel.hidden = !open;
  els.historyToggle.setAttribute('aria-expanded', String(open));
}

/** 页面加载：恢复上次会话的历史，再拉取历史会话列表。 */
async function bootstrap() {
  const stored = readStoredSession();
  if (stored) {
    const result = await loadHistory(stored);
    if (result === 'ok') {
      sessionId = stored;
    } else if (result === 'missing') {
      forgetStoredSession();
    } else if (result === 'unauthorized') {
      return;
    }
  }
  renderSessionId();
  await refreshHistoryList();
  await refreshPreview();
}

// --- 应用预览（见 design.md 决策 3、9、11）---

/**
 * 预览入口地址来自服务端签发的票据（`/preview/<会话>/<票据>/`）。
 * 票据必须放在路径里：预览 iframe 处在不透明源，子资源请求不带登录态 Cookie，
 * 靠 Cookie 取用会被 401 拒绝并被浏览器 ORB 拦掉；相对路径继承同前缀的票据后，
 * 样式与脚本无需 Cookie 即可加载。
 */
function previewTokenUrl() {
  return `/api/sessions/${encodeURIComponent(sessionId)}/preview-token`;
}

function setPreviewState(text) {
  els.previewState.textContent = text || '';
}

/** 展示占位说明并停掉 iframe，避免继续加载上一份应用。 */
function showPreviewPlaceholder(text) {
  els.previewFrame.hidden = true;
  els.previewFrame.src = 'about:blank';
  els.previewPlaceholder.hidden = false;
  els.previewPlaceholder.textContent = text || PREVIEW_EMPTY_TEXT;
}

/** 把 iframe 指向入口页；带时间戳参数确保刷新按钮与回滚后重新加载。 */
function loadPreviewFrame(url) {
  els.previewPlaceholder.hidden = true;
  els.previewFrame.hidden = false;
  els.previewFrame.src = `${url}?t=${Date.now()}`;
}

/** 退出登录或切换会话时把预览复位为初始占位。 */
function resetPreview() {
  setPreviewState('');
  showPreviewPlaceholder(PREVIEW_EMPTY_TEXT);
}

/** 取响应体里的中文 detail，取不到时用兜底文案。 */
async function readDetail(response, fallback) {
  try {
    const body = await response.json();
    if (body && typeof body.detail === 'string') return body.detail;
  } catch (err) {
    /* 非 JSON 响应（例如分享页 HTML），用兜底文案 */
  }
  return fallback;
}

/**
 * 刷新预览：先换取预览票据，据此区分「尚无应用」「加载失败」「登录态失效」，
 * 再用返回的地址把 iframe 指过去（见 tasks.md 4.3）。
 */
async function refreshPreview() {
  if (!sessionId) {
    resetPreview();
    return;
  }

  setPreviewState('正在加载…');
  try {
    const response = await fetch(previewTokenUrl());
    if (response.status === 401) {
      // 登录态失效由集中出口处理，这里不再改预览文案
      handleUnauthorized();
      return;
    }
    if (response.status === 404) {
      showPreviewPlaceholder(await readDetail(response, PREVIEW_EMPTY_TEXT));
      setPreviewState('尚无应用');
      return;
    }
    if (!response.ok) {
      showPreviewPlaceholder('预览加载失败，请稍后点「刷新」重试。');
      setPreviewState(`加载失败（HTTP ${response.status}）`);
      return;
    }
    const payload = await response.json();
    loadPreviewFrame(payload.url);
    setPreviewState('已加载，可直接在右侧操作');
  } catch (err) {
    showPreviewPlaceholder(`预览加载失败：${err.message}`);
    setPreviewState('加载失败');
  }
}

// --- 版本历史（见 design.md 决策 5、8）---

/** 弹层里的提示：统一 error / ok 两种样式。 */
function setTip(el, text, kind) {
  el.textContent = text || '';
  el.classList.toggle('error', kind === 'error');
  el.classList.toggle('ok', kind === 'ok');
}

function versionLabel(versionId, isLatest) {
  return `版本 ${versionId}${isLatest ? '（最新）' : ''}`;
}

/** 取当前会话的版本列表；失败时 versions 为 null 并带上中文原因。 */
async function fetchVersions() {
  const result = await requestJson(
    'GET',
    `/api/sessions/${encodeURIComponent(sessionId)}/versions`
  );
  if (result.status === 401) {
    handleUnauthorized();
    return { versions: null, message: '' };
  }
  if (!result.ok) {
    return { versions: null, message: failureText(result, '版本列表载入失败') };
  }
  return { versions: (result.data && result.data.versions) || [], message: '' };
}

function listMessage(target, text, className) {
  target.innerHTML = '';
  const note = document.createElement('p');
  note.className = className;
  note.textContent = text;
  target.appendChild(note);
}

function renderVersions(versions) {
  els.versionsList.innerHTML = '';
  if (!versions.length) {
    listMessage(els.versionsList, '还没有版本：智能体改动了沙箱内容后会自动留档。', 'list-empty');
    return;
  }

  versions.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'list-item';

    const meta = document.createElement('div');
    meta.className = 'meta';
    const title = document.createElement('span');
    title.className = 'title';
    title.textContent = versionLabel(item.version_id, index === 0);
    const sub = document.createElement('span');
    sub.className = 'sub';
    sub.textContent = formatTime(item.created_at) || '时间未知';
    meta.append(title, sub);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ghost';
    button.textContent = '回滚到该版本';
    button.addEventListener('click', () => rollbackTo(item.version_id, button));

    row.append(meta, button);
    els.versionsList.appendChild(row);
  });
}

async function loadVersions() {
  listMessage(els.versionsList, '正在载入版本…', 'list-empty');
  const { versions, message } = await fetchVersions();
  if (versions === null) {
    els.versionsList.innerHTML = '';
    if (message) setTip(els.versionsTip, message, 'error');
    return;
  }
  renderVersions(versions);
}

async function rollbackTo(versionId, button) {
  const confirmed = window.confirm(
    `确认把当前应用回滚到版本 ${versionId}？\n回滚前的内容会留存为新版本，之后仍可回到回滚前。`
  );
  if (!confirmed) return;

  button.disabled = true;
  setTip(els.versionsTip, '正在回滚…');
  try {
    const result = await requestJson(
      'POST',
      `/api/sessions/${encodeURIComponent(sessionId)}/versions/${encodeURIComponent(
        versionId
      )}/rollback`,
      {}
    );
    if (result.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!result.ok) {
      setTip(els.versionsTip, failureText(result, '回滚失败'), 'error');
      return;
    }
    setTip(els.versionsTip, (result.data && result.data.message) || '已回滚。', 'ok');
    setStatus('已回滚到所选版本，预览已刷新');
    // 沙箱被整体替换，预览与版本列表都要重取
    await refreshPreview();
    await loadVersions();
  } finally {
    button.disabled = false;
  }
}

function openVersionsModal() {
  if (!sessionId) {
    setStatus('还没有会话，先在对话中生成应用再查看版本');
    return;
  }
  els.versionsModal.hidden = false;
  setTip(els.versionsTip, '');
  loadVersions();
}

function closeVersionsModal() {
  els.versionsModal.hidden = true;
  setTip(els.versionsTip, '');
}

// --- 应用分享（见 design.md 决策 6）---

/** 把服务端给的相对地址补成完整链接，便于直接复制发送。 */
function absoluteUrl(url) {
  try {
    return new URL(url, window.location.origin).href;
  } catch (err) {
    return url;
  }
}

function renderShares(items) {
  els.shareList.innerHTML = '';
  if (!items.length) {
    listMessage(els.shareList, '还没有为该会话创建过分享。', 'list-empty');
    return;
  }

  items.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'list-item';

    const meta = document.createElement('div');
    meta.className = 'meta';
    const title = document.createElement('span');
    title.className = 'title';
    title.textContent = versionLabel(item.version_id, false);
    const sub = document.createElement('span');
    sub.className = 'sub';
    sub.textContent = absoluteUrl(item.url);
    sub.title = sub.textContent;
    meta.append(title, sub);

    const copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'ghost';
    copy.textContent = '复制';
    copy.addEventListener('click', async () => {
      const ok = await copyText(absoluteUrl(item.url));
      copy.textContent = ok ? '已复制' : '复制失败';
      setTimeout(() => {
        copy.textContent = '复制';
      }, 1500);
    });

    const revoke = document.createElement('button');
    revoke.type = 'button';
    revoke.className = 'ghost';
    revoke.textContent = '撤销';
    revoke.addEventListener('click', () => revokeShare(item.token, revoke));

    row.append(meta, copy, revoke);
    els.shareList.appendChild(row);
  });
}

async function loadShareVersions() {
  const { versions, message } = await fetchVersions();
  els.shareVersion.innerHTML = '';

  if (versions === null || !versions.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = '暂无可分享的版本';
    els.shareVersion.appendChild(option);
    els.shareVersion.disabled = true;
    els.shareCreate.disabled = true;
    setTip(
      els.shareTip,
      message || '还没有版本：智能体改动沙箱内容后会自动留档，之后即可分享。',
      'error'
    );
    return;
  }

  versions.forEach((item, index) => {
    const option = document.createElement('option');
    option.value = item.version_id;
    const time = formatTime(item.created_at);
    option.textContent = `${versionLabel(item.version_id, index === 0)}${
      time ? ` · ${time}` : ''
    }`;
    els.shareVersion.appendChild(option);
  });
  els.shareVersion.disabled = false;
  els.shareCreate.disabled = false;
}

async function loadShares() {
  const result = await requestJson(
    'GET',
    `/api/sessions/${encodeURIComponent(sessionId)}/shares`
  );
  if (result.status === 401) {
    handleUnauthorized();
    return;
  }
  if (!result.ok) {
    els.shareList.innerHTML = '';
    setTip(els.shareTip, failureText(result, '分享列表载入失败'), 'error');
    return;
  }
  renderShares((result.data && result.data.shares) || []);
}

async function createShare() {
  const versionId = els.shareVersion.value;
  if (!versionId) {
    setTip(els.shareTip, '请先选择一个版本。', 'error');
    return;
  }

  els.shareCreate.disabled = true;
  setTip(els.shareTip, '正在生成分享链接…');
  try {
    const result = await requestJson(
      'POST',
      `/api/sessions/${encodeURIComponent(sessionId)}/shares`,
      { version_id: versionId }
    );
    if (result.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!result.ok) {
      setTip(els.shareTip, failureText(result, '生成分享链接失败'), 'error');
      return;
    }

    const link = absoluteUrl(result.data.share.url);
    const copied = await copyText(link);
    const message = (result.data && result.data.message) || '已生成分享链接。';
    setTip(els.shareTip, copied ? `${message}（链接已复制）` : `${message} 链接：${link}`, 'ok');
    await loadShares();
  } finally {
    els.shareCreate.disabled = !els.shareVersion.value;
  }
}

async function revokeShare(token, button) {
  const confirmed = window.confirm('确认撤销该分享链接？撤销后原链接立即失效。');
  if (!confirmed) return;

  button.disabled = true;
  setTip(els.shareTip, '正在撤销…');
  try {
    const result = await requestJson('DELETE', `/api/shares/${encodeURIComponent(token)}`);
    if (result.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!result.ok) {
      setTip(els.shareTip, failureText(result, '撤销分享失败'), 'error');
      return;
    }
    setTip(els.shareTip, (result.data && result.data.message) || '已撤销该分享链接。', 'ok');
    await loadShares();
  } finally {
    button.disabled = false;
  }
}

function openShareModal() {
  if (!sessionId) {
    setStatus('还没有会话，先在对话中生成应用再分享');
    return;
  }
  els.shareModal.hidden = false;
  setTip(els.shareTip, '');
  listMessage(els.shareList, '正在载入分享…', 'list-empty');
  // 版本下拉与分享列表互不依赖，并行取
  loadShareVersions();
  loadShares();
}

function closeShareModal() {
  els.shareModal.hidden = true;
  setTip(els.shareTip, '');
  els.shareList.innerHTML = '';
}

// --- 内置示例应用（见 specs/example-apps/spec.md 与 design.md 决策 6）---

function renderExamples(items) {
  els.examplesList.innerHTML = '';
  if (!items.length) {
    listMessage(els.examplesList, '暂无可用的内置示例。', 'list-empty');
    return;
  }

  items.forEach((item) => {
    const card = document.createElement('div');
    card.className = 'example-card';

    const name = document.createElement('span');
    name.className = 'example-name';
    name.textContent = item.name;

    const desc = document.createElement('span');
    desc.className = 'example-desc';
    desc.textContent = item.description || '';

    const use = document.createElement('button');
    use.type = 'button';
    use.className = 'primary';
    use.textContent = '使用';
    use.addEventListener('click', () => applyExample(item.id, use));

    card.append(name, desc, use);
    els.examplesList.appendChild(card);
  });
}

async function loadExamples() {
  listMessage(els.examplesList, '正在载入示例…', 'list-empty');
  const result = await requestJson('GET', '/api/examples');
  if (result.status === 401) {
    handleUnauthorized();
    return;
  }
  if (!result.ok) {
    els.examplesList.innerHTML = '';
    setTip(els.examplesTip, failureText(result, '示例列表载入失败'), 'error');
    return;
  }
  renderExamples((result.data && result.data.examples) || []);
}

/** 选用示例：服务端新会话已写好沙箱，这里切过去并刷新预览。 */
async function applyExample(exampleId, button) {
  if (streaming) {
    setTip(els.examplesTip, '正在生成回复，请稍候再选择示例。', 'error');
    return;
  }

  button.disabled = true;
  setTip(els.examplesTip, '正在创建示例会话…');
  try {
    const result = await requestJson('POST', '/api/examples/apply', {
      example_id: exampleId,
    });
    if (result.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!result.ok) {
      setTip(els.examplesTip, failureText(result, '示例创建失败'), 'error');
      return;
    }

    closeExamplesModal();
    clearMessages();
    sessionId = result.data.session_id;
    rememberSession(sessionId);
    renderSessionId();
    highlightActiveSession();
    await refreshHistoryList();
    // 沙箱已由服务端写好，直接刷新预览即可看到成品
    await refreshPreview();
    setStatus((result.data && result.data.message) || '已创建示例应用，可直接预览。');
  } finally {
    button.disabled = false;
  }
}

function openExamplesModal() {
  if (streaming) {
    setStatus('正在生成回复，请稍候再选择示例');
    return;
  }
  els.examplesModal.hidden = false;
  setTip(els.examplesTip, '');
  loadExamples();
}

function closeExamplesModal() {
  els.examplesModal.hidden = true;
  setTip(els.examplesTip, '');
  els.examplesList.innerHTML = '';
}

// --- 界面主题（跟随系统 / 浅色 / 深色，见 design.md 决策 9）---

const THEME_STORAGE_KEY = 'code-assistant.theme';
const THEMES = ['auto', 'light', 'dark'];
const THEME_LABELS = { auto: '主题：自动', light: '主题：浅色', dark: '主题：深色' };

let theme = 'auto';

function readStoredTheme() {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return THEMES.includes(value) ? value : 'auto';
  } catch (err) {
    // 隐私模式下不可读，退回跟随系统
    return 'auto';
  }
}

/** 当前实际生效的是浅色还是深色：auto 时看系统偏好。 */
function resolvedTheme() {
  if (theme !== 'auto') return theme;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

/**
 * 代码高亮主题跟随界面主题（CDN 的 github 样式是浅色底、github-dark 是深色底）。
 * 两份样式表都留在 DOM 里，只切换 disabled，避免切换时重新下载。
 */
function syncCodeTheme() {
  const dark = resolvedTheme() === 'dark';
  if (els.hljsLight) els.hljsLight.disabled = dark;
  if (els.hljsDark) els.hljsDark.disabled = !dark;
}

/** auto 时不设 data-theme（交由 prefers-color-scheme），否则显式覆盖。 */
function applyTheme(value) {
  theme = THEMES.includes(value) ? value : 'auto';
  const root = document.documentElement;
  if (theme === 'auto') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
  els.themeToggle.textContent = THEME_LABELS[theme];
  els.themeToggle.title = `界面主题：${THEME_LABELS[theme].slice(3)}（点击在自动 / 浅色 / 深色间切换）`;
  syncCodeTheme();
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch (err) {
    /* 隐私模式下不可写，本次选择仅在本次会话生效 */
  }
}

function cycleTheme() {
  applyTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]);
}

// --- 认证 ---

const AUTH_MODE_TEXT = {
  login: { submit: '登录', autocomplete: 'current-password' },
  register: { submit: '注册', autocomplete: 'new-password' },
};

const BAD_CREDENTIALS_TIP = '用户名或密码错误。';
const UNAUTHORIZED_TIP = '登录状态已失效，请重新登录。';
const CHANGE_PASSWORD_HINT = '修改密码需要先登录：登录后可在对话界面顶栏的「修改密码」中修改。';

function setAuthTip(text, kind) {
  els.authTip.textContent = text || '';
  els.authTip.classList.toggle('error', kind === 'error');
  els.authTip.classList.toggle('ok', kind === 'ok');
}

/** 切换认证表单；切换与取消都会清空已输入的密码。 */
function setAuthMode(mode) {
  authMode = mode;
  const text = AUTH_MODE_TEXT[mode];
  els.authModeLogin.classList.toggle('active', mode === 'login');
  els.authModeRegister.classList.toggle('active', mode === 'register');
  els.authSubmit.textContent = text.submit;
  els.authPassword.setAttribute('autocomplete', text.autocomplete);
  els.authPassword.value = '';
  setAuthTip('');
}

/** 未登录（或登录态失效）时的唯一界面。 */
function showAuth(tip) {
  sessionId = null;
  currentUsername = '';
  forgetStoredSession();
  closePasswordModal();
  closeVersionsModal();
  closeShareModal();
  closeExamplesModal();
  resetPreview();
  els.chatApp.hidden = true;
  els.authApp.hidden = false;
  setAuthTip(tip || '');
  els.authUsername.focus();
}

/** 登录成功后进入对话界面。 */
function enterChat(identity) {
  const username = (identity && identity.username) || '';
  const role = identity && identity.role === 'admin' ? '（管理员）' : '';
  currentUsername = username;
  els.currentUser.textContent = username ? `当前用户：${username}${role}` : '';
  els.currentUser.title = username ? `当前登录用户：${username}${role}` : '当前登录用户';
  els.passwordModalUser.textContent = username
    ? `将修改账号「${username}${role}」的密码，其他设备上的登录态会立即失效。`
    : '';
  els.authApp.hidden = true;
  els.chatApp.hidden = false;
  bootstrap();
}

/** 任何受保护接口返回 401 时的统一出口：回到认证界面并提示重新登录。 */
function handleUnauthorized() {
  showAuth(UNAUTHORIZED_TIP);
}

/** 统一请求：取出 detail，网络异常也归一化为失败结果；DELETE / GET 共用同一出口。 */
async function requestJson(method, path, body) {
  const options = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) options.body = JSON.stringify(body);
  try {
    const response = await fetch(path, options);
    let data = null;
    try {
      data = await response.json();
    } catch (err) {
      data = null;
    }
    const detail = data && typeof data.detail === 'string' ? data.detail : '';
    return { ok: response.ok, status: response.status, data, detail };
  } catch (err) {
    return { ok: false, status: 0, data: null, detail: `无法连接到服务：${err.message}` };
  }
}

function postJson(path, body) {
  return requestJson('POST', path, body || {});
}

function failureText(result, fallback) {
  return result.detail || `${fallback}（HTTP ${result.status}）`;
}

async function submitAuth(event) {
  event.preventDefault();
  const username = els.authUsername.value.trim();
  const password = els.authPassword.value;

  if (!username) {
    setAuthTip('请填写用户名。', 'error');
    return;
  }
  if (!password) {
    setAuthTip('请填写密码。', 'error');
    return;
  }

  els.authSubmit.disabled = true;
  try {
    if (authMode === 'register') {
      const result = await postJson('/api/auth/register', { username, password });
      if (!result.ok) {
        setAuthTip(failureText(result, '注册失败'), 'error');
        return;
      }
      setAuthMode('login');
      setAuthTip((result.data && result.data.message) || '注册成功，请登录。', 'ok');
      return;
    }

    const result = await postJson('/api/auth/login', { username, password });
    if (result.status === 401) {
      setAuthTip(BAD_CREDENTIALS_TIP, 'error');
      return;
    }
    if (!result.ok) {
      setAuthTip(failureText(result, '登录失败'), 'error');
      return;
    }
    enterChat(result.data);
  } finally {
    els.authSubmit.disabled = false;
  }
}

// --- 修改密码（仅已登录用户；见 design.md 决策 11）---

function setPasswordTip(text, kind) {
  els.passwordTip.textContent = text || '';
  els.passwordTip.classList.toggle('error', kind === 'error');
  els.passwordTip.classList.toggle('ok', kind === 'ok');
}

function openPasswordModal() {
  els.passwordOld.value = '';
  els.passwordNew.value = '';
  setPasswordTip('');
  els.passwordModal.hidden = false;
  els.passwordOld.focus();
}

function closePasswordModal() {
  els.passwordModal.hidden = true;
  els.passwordOld.value = '';
  els.passwordNew.value = '';
  setPasswordTip('');
}

async function submitPasswordChange(event) {
  event.preventDefault();
  const oldPassword = els.passwordOld.value;
  const newPassword = els.passwordNew.value;

  if (!oldPassword) {
    setPasswordTip('请填写原密码。', 'error');
    return;
  }
  if (!newPassword) {
    setPasswordTip('请填写新密码。', 'error');
    return;
  }

  els.passwordSubmit.disabled = true;
  try {
    const result = await postJson('/api/auth/password', {
      old_password: oldPassword,
      new_password: newPassword,
    });
    if (result.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!result.ok) {
      setPasswordTip(failureText(result, '修改密码失败'), 'error');
      return;
    }
    closePasswordModal();
    setStatus((result.data && result.data.message) || '密码已修改，其他登录态已失效。');
  } finally {
    els.passwordSubmit.disabled = false;
  }
}

async function logout() {
  els.logout.disabled = true;
  try {
    await postJson('/api/auth/logout', {});
  } finally {
    els.logout.disabled = false;
    els.authUsername.value = '';
    setAuthMode('login');
    showAuth('已退出登录。');
  }
}

/** 页面加载门控：先确认登录态，成功才进入对话界面。 */
async function start() {
  setAuthMode('login');
  // 主题是纯本地偏好，先于登录态生效，避免未登录时闪烁
  applyTheme(readStoredTheme());
  try {
    const response = await fetch('/api/auth/me');
    if (response.ok) {
      enterChat(await response.json());
      return;
    }
    showAuth(
      response.status === 401 ? '' : `无法确认登录状态（HTTP ${response.status}），请重新登录。`
    );
  } catch (err) {
    showAuth(`无法连接到服务：${err.message}`);
  }
}

function bindEvents() {
  els.authForm.addEventListener('submit', submitAuth);
  els.authCancel.addEventListener('click', () => setAuthMode('login'));
  els.authModeLogin.addEventListener('click', () => setAuthMode('login'));
  els.authModeRegister.addEventListener('click', () => setAuthMode('register'));
  // 未登录时改密不被允许，这里只作入口提示，不进入任何可提交的改密表单
  els.authModePassword.addEventListener('click', () => {
    setAuthMode('login');
    setAuthTip(CHANGE_PASSWORD_HINT);
    els.authUsername.focus();
  });
  els.changePassword.addEventListener('click', openPasswordModal);
  els.passwordForm.addEventListener('submit', submitPasswordChange);
  els.passwordCancel.addEventListener('click', closePasswordModal);
  els.logout.addEventListener('click', logout);
  els.send.addEventListener('click', send);
  els.interrupt.addEventListener('click', interrupt);
  els.themeToggle.addEventListener('click', cycleTheme);
  // 跟随系统时：系统主题变化也要同步代码高亮样式
  if (window.matchMedia) {
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      if (theme === 'auto') syncCodeTheme();
    };
    if (query.addEventListener) query.addEventListener('change', onChange);
    else if (query.addListener) query.addListener(onChange);
  }
  els.examplesOpen.addEventListener('click', openExamplesModal);
  els.examplesClose.addEventListener('click', closeExamplesModal);
  els.newSession.addEventListener('click', startNewSession);
  els.downloadProject.addEventListener('click', downloadProject);
  els.historyToggle.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleHistory();
  });
  els.historyRefresh.addEventListener('click', refreshHistoryList);
  els.historyPanel.addEventListener('click', (event) => event.stopPropagation());
  document.addEventListener('click', () => toggleHistory(false));
  els.previewRefresh.addEventListener('click', refreshPreview);
  els.versionsOpen.addEventListener('click', openVersionsModal);
  els.versionsClose.addEventListener('click', closeVersionsModal);
  els.shareOpen.addEventListener('click', openShareModal);
  els.shareCreate.addEventListener('click', createShare);
  els.shareClose.addEventListener('click', closeShareModal);
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    toggleHistory(false);
    if (!els.passwordModal.hidden) closePasswordModal();
    if (!els.versionsModal.hidden) closeVersionsModal();
    if (!els.shareModal.hidden) closeShareModal();
    if (!els.examplesModal.hidden) closeExamplesModal();
  });
  els.input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      send();
    }
  });
}

bindEvents();
start();