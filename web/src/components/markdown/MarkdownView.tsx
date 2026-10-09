// 唯一使用 dangerouslySetInnerHTML 的组件：marked 渲染 → DOMPurify 清洗 → 注入。
// 代码块的「复制 / 另存为」按钮不写进 HTML 字符串，而是渲染后遍历 pre > code 挂上轻量操作条，
// 避免用户内容伪造操作按钮（见 design.md 决策 7）。渲染失败时退化为纯文本，不白屏。

import { useEffect, useMemo, useRef } from 'react';

import DOMPurify from 'dompurify';
import hljs from 'highlight.js/lib/common';
import { marked } from 'marked';

import { copyText, saveBlob } from '../../utils';

marked.setOptions({ gfm: true, breaks: true });

const LANG_LABELS: Record<string, string> = {
  java: 'Java',
  python: 'Python',
  csharp: 'C#',
  cpp: 'C++',
  html: 'HTML',
  javascript: 'JavaScript',
};

const LANG_EXTENSIONS: Record<string, string> = {
  java: 'java',
  python: 'py',
  csharp: 'cs',
  cpp: 'cpp',
  html: 'html',
  javascript: 'js',
};

const MAX_LANG_LABEL_LEN = 12;

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderSanitized(markdown: string): string {
  const source = markdown || '';
  try {
    const raw = marked.parse(source, { async: false }) as string;
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  } catch {
    return `<pre class="plain-text">${escapeHtml(source)}</pre>`;
  }
}

function detectLanguage(codeEl: Element): string {
  const match = /language-([\w+#-]+)/i.exec(codeEl.className || '');
  const raw = match ? match[1].toLowerCase() : '';
  if (raw === 'c#' || raw === 'cs') return 'csharp';
  if (raw === 'c++' || raw === 'cc' || raw === 'cxx') return 'cpp';
  if (raw === 'js') return 'javascript';
  return raw.slice(0, MAX_LANG_LABEL_LEN);
}

/** 同一次渲染内出现同名文件时追加序号，避免重复下载覆盖。 */
function uniqueFileName(base: string, ext: string, used: Map<string, number>): string {
  const count = (used.get(ext) || 0) + 1;
  used.set(ext, count);
  return count === 1 ? `${base}.${ext}` : `${base}-${count}.${ext}`;
}

function makeToolButton(label: string, title: string, onClick: () => void): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'code-copy';
  button.textContent = label;
  button.title = title;
  button.addEventListener('click', onClick);
  return button;
}

function enhanceCodeBlocks(root: HTMLElement): void {
  const usedNames = new Map<string, number>();

  root.querySelectorAll('pre > code').forEach((codeEl) => {
    if (codeEl.closest('.code-block')) return;

    const language = detectLanguage(codeEl);
    const source = codeEl.textContent || '';

    codeEl.classList.add('hljs');
    // 未标注语言时保持纯文本展示，不做自动探测，避免流式过程中的额外开销
    if (language && hljs.getLanguage(language)) {
      codeEl.innerHTML = hljs.highlight(source, { language }).value;
    }

    const block = document.createElement('div');
    block.className = 'code-block';

    const head = document.createElement('div');
    head.className = 'code-head';

    const label = document.createElement('span');
    label.className = 'code-lang';
    label.textContent = LANG_LABELS[language] || language || '纯文本';

    const copyBtn = makeToolButton('复制', '复制该代码块', async () => {
      const ok = await copyText(source);
      copyBtn.textContent = ok ? '已复制' : '复制失败';
      setTimeout(() => {
        copyBtn.textContent = '复制';
      }, 1500);
    });

    const fileName = uniqueFileName('snippet', LANG_EXTENSIONS[language] || 'txt', usedNames);
    const saveBtn = makeToolButton('另存为', `保存为 ${fileName}`, () => {
      saveBlob(new Blob([source], { type: 'text/plain;charset=utf-8' }), fileName);
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
    if (!pre) return;
    pre.replaceWith(block);
    block.append(head, pre);
  });
}

export default function MarkdownView({ markdown }: { markdown: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const html = useMemo(() => renderSanitized(markdown), [markdown]);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    enhanceCodeBlocks(root);
  }, [html]);

  return <div className="markdown-body" ref={ref} dangerouslySetInnerHTML={{ __html: html }} />;
}