// 前端逻辑：SSE 消费、Markdown 与代码块渲染、会话恢复与历史会话切换

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

const els = {
  messages: document.getElementById('messages'),
  input: document.getElementById('input'),
  send: document.getElementById('send'),
  language: document.getElementById('language'),
  newSession: document.getElementById('new-session'),
  downloadProject: document.getElementById('download-project'),
  historyToggle: document.getElementById('history-toggle'),
  historyPanel: document.getElementById('history-panel'),
  historyList: document.getElementById('history-list'),
  historyRefresh: document.getElementById('history-refresh'),
  status: document.getElementById('status'),
  sessionId: document.getElementById('session-id'),
};

let sessionId = null;
let streaming = false;

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
    '<p>描述你要实现的功能、粘贴一段待解释或待重构的代码、或贴上代码让助手排查问题。</p>';
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

function showError(contentEl, message) {
  const tip = document.createElement('div');
  tip.className = 'error-tip';
  tip.textContent = message;
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

async function send() {
  const text = els.input.value.trim();
  if (!text || streaming) return;

  els.input.value = '';
  addMessage('user', text);
  const contentEl = addMessage('assistant', '');

  streaming = true;
  els.send.disabled = true;
  setStatus('生成中…');

  let raw = '';
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

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
        target_language: els.language.value || null,
      }),
    });

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
          scheduleRender();
        } else if (frame.type === 'error') {
          showError(contentEl, frame.data.message || '服务端返回错误');
        } else if (frame.type === 'done') {
          if (frame.data && frame.data.session_id) sessionId = frame.data.session_id;
        }
      }
    }

    renderNow();
    if (!raw) {
      showError(contentEl, '本轮没有收到任何内容，请重试。');
    }
    renderSessionId();
    if (sessionId) {
      rememberSession(sessionId);
      await refreshHistoryList();
    }
  } catch (err) {
    renderNow();
    showError(contentEl, `连接中断或服务端异常：${err.message}`);
  } finally {
    streaming = false;
    els.send.disabled = false;
    setStatus('');
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

/** 载入历史消息：ok / missing（会话已不存在）/ error。 */
async function loadHistory(id) {
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(id)}/messages`);
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
    } else {
      setStatus('历史会话载入失败，请稍后重试');
      return;
    }
    renderSessionId();
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
    }
  }
  renderSessionId();
  await refreshHistoryList();
}

function bindEvents() {
  els.send.addEventListener('click', send);
  els.newSession.addEventListener('click', startNewSession);
  els.downloadProject.addEventListener('click', downloadProject);
  els.historyToggle.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleHistory();
  });
  els.historyRefresh.addEventListener('click', refreshHistoryList);
  els.historyPanel.addEventListener('click', (event) => event.stopPropagation());
  document.addEventListener('click', () => toggleHistory(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') toggleHistory(false);
  });
  els.input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      send();
    }
  });
}

bindEvents();
bootstrap();