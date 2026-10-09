// 对话流：消息列表、打字机增量渲染（含完整帧兜底）、执行进度、主动中断与失败重试。
// 语义与迁移前一致（见 specs/web-chat 的「迁移后既有交互语义不变」）。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { streamChat } from '../api/chat';
import type { HistoryMessage } from '../types';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  /** 本轮以失败 / 中断收尾时的中文说明。 */
  error?: string;
  /** 是否可「重试」（主动中断不给重试按钮）。 */
  retryable?: boolean;
  /** 重试时原样重发的用户消息。 */
  retryText?: string;
}

export type TurnResult = 'done' | 'interrupted' | 'error';

export interface ChatStreamApi {
  messages: ChatMessage[];
  streaming: boolean;
  progress: string;
  setMessages: (messages: ChatMessage[]) => void;
  reset: () => void;
  send: (text: string) => Promise<void>;
  retry: (messageId: string) => Promise<void>;
  interrupt: () => void;
}

const ABORT_TEXT =
  '已中断本轮生成。已写入沙箱的部分内容仍保留，可重新发送；若这是新会话，可在「历史会话」中找到它继续补齐。';

let sequence = 0;
function nextId(): string {
  sequence += 1;
  return `m${sequence}`;
}

/** 把历史接口返回的消息转为界面消息。 */
export function toChatMessages(history: HistoryMessage[]): ChatMessage[] {
  return history.map((item) => ({ id: nextId(), role: item.role, text: item.text }));
}

interface Options {
  sessionId: string | null;
  onTurnEnd: (result: TurnResult, createdSessionId: string | null) => void;
}

export function useChatStream(options: Options): ChatStreamApi {
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const [messages, setMessagesState] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [progress, setProgress] = useState('');

  const messagesRef = useRef<ChatMessage[]>([]);
  const streamingRef = useRef(false);
  const interruptedRef = useRef(false);
  const controllerRef = useRef<AbortController | null>(null);
  const progressTimerRef = useRef<number | null>(null);
  const streamRawRef = useRef('');
  const turnStartRef = useRef(0);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const patchMessage = useCallback((id: string, patch: Partial<ChatMessage>) => {
    setMessagesState((prev) => prev.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }, []);

  const stopProgress = useCallback(() => {
    if (progressTimerRef.current !== null) {
      clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
  }, []);

  /** 状态区显示「正在生成第 N 行 · 已用 M 秒」，让使用者知道后台在推进。 */
  const renderProgress = useCallback(() => {
    const seconds = Math.floor((Date.now() - turnStartRef.current) / 1000);
    const lines = streamRawRef.current ? streamRawRef.current.split('\n').length : 0;
    setProgress(
      lines
        ? `正在生成第 ${lines} 行 · 已用 ${seconds} 秒`
        : `正在等待模型响应 · 已用 ${seconds} 秒`,
    );
  }, []);

  const runTurn = useCallback(
    async (text: string) => {
      if (streamingRef.current) return;

      const assistantId = nextId();
      setMessagesState((prev) => [...prev, { id: assistantId, role: 'assistant', text: '' }]);

      streamingRef.current = true;
      setStreaming(true);
      interruptedRef.current = false;
      streamRawRef.current = '';
      turnStartRef.current = Date.now();
      renderProgress();
      stopProgress();
      progressTimerRef.current = window.setInterval(renderProgress, 500);

      const controller = new AbortController();
      controllerRef.current = controller;

      let raw = '';
      let errorMessage = '';
      let createdSessionId: string | null = null;
      let renderTimer: number | null = null;

      const flush = () => patchMessage(assistantId, { text: raw });
      const scheduleFlush = () => {
        if (renderTimer !== null) return;
        renderTimer = window.setTimeout(() => {
          renderTimer = null;
          flush();
        }, 100);
      };
      const flushNow = () => {
        if (renderTimer !== null) {
          clearTimeout(renderTimer);
          renderTimer = null;
        }
        flush();
      };

      let result: TurnResult = 'done';
      try {
        await streamChat(
          { message: text, sessionId: optionsRef.current.sessionId },
          {
            onText: (chunk, partial) => {
              raw = partial ? raw + chunk : chunk;
              streamRawRef.current = raw;
              scheduleFlush();
            },
            onError: (_code, message) => {
              errorMessage = message || '服务端返回错误';
            },
            onDone: (sessionId) => {
              if (sessionId) createdSessionId = sessionId;
            },
          },
          controller.signal,
        );
        controllerRef.current = null;
        flushNow();
        if (errorMessage) {
          // 任何错误帧（超时 / 限流 / 上游报错）都给出「重试」入口
          patchMessage(assistantId, { error: errorMessage, retryable: true, retryText: text });
        } else if (!raw) {
          patchMessage(assistantId, {
            error: '本轮没有收到任何内容，请重试。',
            retryable: true,
            retryText: text,
          });
        }
      } catch (err) {
        flushNow();
        if (interruptedRef.current) {
          result = 'interrupted';
          patchMessage(assistantId, { error: ABORT_TEXT, retryable: false });
        } else {
          result = 'error';
          patchMessage(assistantId, {
            error: `连接中断或服务端异常：${(err as Error).message}`,
            retryable: true,
            retryText: text,
          });
        }
      } finally {
        stopProgress();
        controllerRef.current = null;
        streamingRef.current = false;
        setStreaming(false);
        optionsRef.current.onTurnEnd(result, createdSessionId);
      }
    },
    [patchMessage, renderProgress, stopProgress],
  );

  const send = useCallback(
    async (text: string) => {
      if (streamingRef.current) return;
      const trimmed = text.trim();
      if (!trimmed) return;
      setMessagesState((prev) => [...prev, { id: nextId(), role: 'user', text: trimmed }]);
      await runTurn(trimmed);
    },
    [runTurn],
  );

  /** 重试：移除失败的回复气泡，把同一条用户消息原样重发。 */
  const retry = useCallback(
    async (messageId: string) => {
      if (streamingRef.current) return;
      const target = messagesRef.current.find((item) => item.id === messageId);
      const text = target?.retryText;
      if (!text) return;
      setMessagesState((prev) => prev.filter((item) => item.id !== messageId));
      await runTurn(text);
    },
    [runTurn],
  );

  const interrupt = useCallback(() => {
    if (!streamingRef.current || !controllerRef.current) return;
    interruptedRef.current = true;
    controllerRef.current.abort();
    setProgress('正在中断…');
  }, []);

  const setMessages = useCallback((next: ChatMessage[]) => {
    setMessagesState(next);
  }, []);

  const reset = useCallback(() => {
    setMessagesState([]);
  }, []);

  return useMemo<ChatStreamApi>(
    () => ({ messages, streaming, progress, setMessages, reset, send, retry, interrupt }),
    [messages, streaming, progress, setMessages, reset, send, retry, interrupt],
  );
}