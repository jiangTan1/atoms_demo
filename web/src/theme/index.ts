// 主题令牌与三态主题解析：品牌色、圆角、字号、间距由 ConfigProvider 统一下发，
// 界面各处不再散落字面量（见 design.md 决策 5、specs/web-ui-design-system）。

import type { ThemeConfig } from 'antd';

/** 集中定义的 antd 设计令牌。 */
export const brandToken: ThemeConfig['token'] = {
  colorPrimary: '#1677ff',
  borderRadius: 8,
  fontSize: 14,
  controlHeight: 36,
  padding: 16,
};

export const THEME_STORAGE_KEY = 'code-assistant.theme';

export type ThemeMode = 'auto' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

export const THEME_MODES: ThemeMode[] = ['auto', 'light', 'dark'];

export const THEME_LABELS: Record<ThemeMode, string> = {
  auto: '自动',
  light: '浅色',
  dark: '深色',
};

/** 读取本机记住的主题；不可读或取值非法时退回「自动」。 */
export function readStoredTheme(): ThemeMode {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === 'light' || value === 'dark' || value === 'auto' ? value : 'auto';
  } catch {
    return 'auto';
  }
}

export function writeStoredTheme(mode: ThemeMode): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    /* 隐私模式下不可写，本次选择仅在本次会话生效 */
  }
}

export function systemPrefersDark(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  );
}