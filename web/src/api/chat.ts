// /api/chat 的 SSE 流解析：按 `data: {json}\n\n` 逐帧切分并回调，
// 支持 AbortController 中断，区分「正常结束」与「错误帧」（见 design.md 决策 6）。

import type { Frame } from '../types';
import { ApiError, notifyUnauthorized, readDetail } from './client';

export interface ChatHandlers {
  onText: (text: string, partial: boolean) => void;
  onError: (code: string, message: string) => void;
  onDone: (sessionId: string) => void;
}

export interface ChatParams {
  message: string;
  sessionId: string | null;
  targetLanguage?: string | null;
}

/** 把一段 SSE 分块解析为帧；解析失败返回 null 并跳过该块。 */
function parseFrame(chunk: string): Frame | null {
  const payload = chunk
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
    .join('');
  if (!payload) return null;
  try {
    return JSON.parse(payload) as Frame;
  } catch {
    return null;
  }
}

export async function streamChat(
  params: ChatParams,
  handlers: ChatHandlers,
  signal: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: params.message,
        session_id: params.sessionId,
        target_language: params.targetLanguage ?? null,
      }),
      credentials: 'same-origin',
      signal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(`无法连接到服务：${(err as Error).message}`, 0);
  }

  if (response.status === 401) {
    notifyUnauthorized();
    throw new ApiError('登录状态已失效，请重新登录。', 401, await readDetail(response));
  }
  if (!response.ok || !response.body) {
    const detail = await readDetail(response);
    throw new ApiError(
      detail
        ? `请求失败（HTTP ${response.status}）：${detail}`
        : `请求失败（HTTP ${response.status}）`,
      response.status,
      detail,
    );
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
        handlers.onText(frame.data, frame.partial);
      } else if (frame.type === 'error') {
        handlers.onError(frame.data.code, frame.data.message);
      } else if (frame.type === 'done') {
        handlers.onDone(frame.data.session_id);
      }
    }
  }
}