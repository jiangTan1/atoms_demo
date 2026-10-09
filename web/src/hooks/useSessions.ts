// 会话能力：当前会话标识、历史会话列表与历史消息读取。
// 新建会话仍是惰性的——首次提问时由服务端创建，避免历史列表里堆出空会话。

import { useCallback, useMemo, useState } from 'react';

import { ApiError, request } from '../api/client';
import type {
  HistoryMessage,
  SessionListResponse,
  SessionMessagesResponse,
  SessionSummary,
} from '../types';

const SESSION_STORAGE_KEY = 'code-assistant.session_id';

export interface LoadResult {
  status: 'ok' | 'missing' | 'error';
  messages: HistoryMessage[];
}

export interface SessionsApi {
  sessionId: string | null;
  sessions: SessionSummary[];
  setSessionId: (id: string | null) => void;
  refreshList: () => Promise<void>;
  loadMessages: (id: string) => Promise<LoadResult>;
}

/** 读取上次记住的会话标识；不可读时返回 null。 */
export function readStoredSession(): string | null {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredSession(id: string | null): void {
  try {
    if (id) localStorage.setItem(SESSION_STORAGE_KEY, id);
    else localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    /* 隐私模式下不可写，忽略即可，不影响对话 */
  }
}

export function useSessions(): SessionsApi {
  const [sessionId, setSessionIdState] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);

  const setSessionId = useCallback((id: string | null) => {
    setSessionIdState(id);
    writeStoredSession(id);
  }, []);

  const refreshList = useCallback(async () => {
    try {
      const payload = await request<SessionListResponse>('GET', '/api/sessions');
      setSessions(payload.sessions ?? []);
    } catch {
      /* 列表拉取失败不影响对话本身 */
    }
  }, []);

  const loadMessages = useCallback(async (id: string): Promise<LoadResult> => {
    try {
      const payload = await request<SessionMessagesResponse>(
        'GET',
        `/api/sessions/${encodeURIComponent(id)}/messages`,
      );
      return { status: 'ok', messages: payload.messages ?? [] };
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return { status: 'missing', messages: [] };
      return { status: 'error', messages: [] };
    }
  }, []);

  return useMemo<SessionsApi>(
    () => ({ sessionId, sessions, setSessionId, refreshList, loadMessages }),
    [sessionId, sessions, setSessionId, refreshList, loadMessages],
  );
}