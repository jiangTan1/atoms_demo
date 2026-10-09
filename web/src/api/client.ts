// fetch 封装：同源凭据、JSON 解析、401 集中处理（见 design.md 决策 8）。
// 任何受保护接口返回 401 时，统一经由注册的 unauthorized 出口切回认证界面，
// 避免各组件各写一份登录态失效逻辑。

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(message: string, status: number, detail = '') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

/** 由认证层注册：收到 401 时清理登录态并切回认证界面。 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

export function notifyUnauthorized(): void {
  unauthorizedHandler?.();
}

/** 从响应体里取中文说明：优先 detail，其次 message。 */
export async function readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown; message?: unknown };
    if (body && typeof body.detail === 'string') return body.detail;
    if (body && typeof body.message === 'string') return body.message;
  } catch {
    /* 非 JSON 响应（例如分享页 HTML）走兜底文案 */
  }
  return '';
}

export interface RequestOptions {
  /** 登录接口自身也会返回 401（凭据错误），这些请求不触发全局登录态失效出口。 */
  skipAuthHandler?: boolean;
  signal?: AbortSignal;
}

/** 把失败响应归一化为带中文说明的 ApiError。 */
export async function toError(response: Response): Promise<ApiError> {
  const detail = await readDetail(response);
  const message = detail
    ? `请求失败（HTTP ${response.status}）：${detail}`
    : `请求失败（HTTP ${response.status}）`;
  return new ApiError(message, response.status, detail);
}

export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      signal: options.signal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(`无法连接到服务：${(err as Error).message}`, 0);
  }

  if (response.status === 401 && !options.skipAuthHandler) {
    notifyUnauthorized();
    throw new ApiError('登录状态已失效，请重新登录。', 401, await readDetail(response));
  }
  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;

  try {
    return (await response.json()) as T;
  } catch {
    return undefined as T;
  }
}

/** 下载类请求：返回二进制内容与响应头给出的文件名。 */
export async function requestBlob(
  path: string,
  fallbackName: string,
  options: RequestOptions = {},
): Promise<{ blob: Blob; filename: string }> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: 'same-origin', signal: options.signal });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(`无法连接到服务：${(err as Error).message}`, 0);
  }

  if (response.status === 401 && !options.skipAuthHandler) {
    notifyUnauthorized();
    throw new ApiError('登录状态已失效，请重新登录。', 401, await readDetail(response));
  }
  if (!response.ok) throw await toError(response);

  const header = response.headers.get('content-disposition') || '';
  const match = /filename="?([^";]+)"?/i.exec(header);
  return { blob: await response.blob(), filename: match ? match[1] : fallbackName };
}