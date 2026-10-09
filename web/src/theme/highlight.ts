// 代码高亮主题随界面主题切换：把两份 highlight.js 样式作为字符串内联注入，
// 靠 <style> 的 disabled 切换，避免切换时重新下载，也不再依赖运行时 CDN（见 design.md 决策 5）。

import lightCss from 'highlight.js/styles/github.css?inline';
import darkCss from 'highlight.js/styles/github-dark.css?inline';

const LIGHT_ID = 'hljs-theme-light';
const DARK_ID = 'hljs-theme-dark';

function ensureStyle(id: string, css: string): HTMLStyleElement {
  let element = document.getElementById(id) as HTMLStyleElement | null;
  if (!element) {
    element = document.createElement('style');
    element.id = id;
    element.textContent = css;
    document.head.appendChild(element);
  }
  return element;
}

/** 应用代码高亮配色：浅色启用 github，深色启用 github-dark。 */
export function applyCodeTheme(dark: boolean): void {
  const light = ensureStyle(LIGHT_ID, lightCss);
  const darkEl = ensureStyle(DARK_ID, darkCss);
  light.disabled = dark;
  darkEl.disabled = !dark;
}