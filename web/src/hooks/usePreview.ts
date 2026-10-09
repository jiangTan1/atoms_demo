// 应用预览：刷新时先换取预览票据，据此区分「尚无应用」「加载失败」「登录态失效」，
// 再用返回的地址把 iframe 指过去（见 design.md 决策 8 与 specs 的既有语义）。

import { useCallback, useMemo, useState } from 'react';

import { ApiError, request } from '../api/client';
import type { PreviewTokenResponse } from '../types';

export const PREVIEW_EMPTY_TEXT =
  '还没有可预览的应用。在左侧描述你想要的网页应用（例如「做一个俄罗斯方块小游戏」），生成后这里会显示它，并可以直接操作。';

export interface PreviewApi {
  /** 可交给 iframe 的入口地址（已带刷新用的时间戳）；无应用时为 null。 */
  url: string | null;
  /** 无应用或加载失败时展示的占位说明。 */
  placeholder: string;
  /** 预览区状态文案。 */
  stateText: string;
  refresh: (sessionId: string | null) => Promise<void>;
}

export function usePreview(): PreviewApi {
  const [url, setUrl] = useState<string | null>(null);
  const [placeholder, setPlaceholder] = useState(PREVIEW_EMPTY_TEXT);
  const [stateText, setStateText] = useState('');

  const refresh = useCallback(async (sessionId: string | null) => {
    if (!sessionId) {
      setUrl(null);
      setPlaceholder(PREVIEW_EMPTY_TEXT);
      setStateText('');
      return;
    }

    setStateText('正在加载…');
    try {
      const payload = await request<PreviewTokenResponse>(
        'GET',
        `/api/sessions/${encodeURIComponent(sessionId)}/preview-token`,
      );
      // 时间戳确保刷新按钮与回滚后重新加载同一地址
      setUrl(`${payload.url}?t=${Date.now()}`);
      setStateText('已加载，可直接在右侧操作');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return; // 已由集中出口处理
      setUrl(null);
      if (err instanceof ApiError && err.status === 404) {
        setPlaceholder(err.detail || PREVIEW_EMPTY_TEXT);
        setStateText('尚无应用');
        return;
      }
      const message = err instanceof ApiError ? err.message : (err as Error).message;
      setPlaceholder(`预览加载失败：${message}`);
      setStateText(err instanceof ApiError && err.status ? `加载失败（HTTP ${err.status}）` : '加载失败');
    }
  }, []);

  return useMemo<PreviewApi>(
    () => ({ url, placeholder, stateText, refresh }),
    [url, placeholder, stateText, refresh],
  );
}