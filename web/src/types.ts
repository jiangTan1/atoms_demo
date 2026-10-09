// 与后端一一对应的接口类型。字段名、可选性逐项对照 app/schemas.py 与 app/services/chat.py，
// 作为前端侧的单一事实来源（见 design.md 决策 3）。

export type TargetLanguage =
  | 'java'
  | 'python'
  | 'csharp'
  | 'cpp'
  | 'html'
  | 'javascript';

// --- 认证 ---

export interface Identity {
  username: string;
  role: string;
}

export interface AuthMessage {
  message: string;
}

// --- 会话 ---

export interface SessionSummary {
  session_id: string;
  title: string;
  updated_at: number;
  message_count: number;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
}

export interface HistoryMessage {
  role: 'user' | 'assistant';
  text: string;
}

export interface SessionMessagesResponse {
  session_id: string;
  user_id: string;
  messages: HistoryMessage[];
}

// --- 应用预览 ---

export interface PreviewTokenResponse {
  token: string;
  url: string;
  expires_in: number;
}

// --- 应用版本 ---

export interface VersionItem {
  version_id: string;
  created_at: number;
}

export interface VersionListResponse {
  session_id: string;
  versions: VersionItem[];
}

export interface RollbackResponse {
  session_id: string;
  version_id: string;
  preserved_version_id: string | null;
  message: string;
}

// --- 预置示例应用 ---

export interface ExampleItem {
  id: string;
  name: string;
  description: string;
}

export interface ExampleListResponse {
  examples: ExampleItem[];
}

export interface ExampleApplyResponse {
  session_id: string;
  example_id: string;
  message: string;
}

// --- 应用分享 ---

export interface ShareItem {
  token: string;
  version_id: string;
  created_at: number;
  url: string;
}

export interface ShareCreateResponse {
  share: ShareItem;
  message: string;
}

export interface ShareListResponse {
  shares: ShareItem[];
}

export interface ShareRevokeResponse {
  token: string;
  message: string;
}

// --- SSE 帧（app/schemas.py 的 Frame / TextFrame / ErrorFrame / DoneFrame） ---

export type ErrorCode = 'auth_error' | 'network_error' | 'upstream_error';

export interface TextFrame {
  type: 'text';
  data: string;
  partial: boolean;
}

export interface ErrorFrame {
  type: 'error';
  data: { code: ErrorCode | string; message: string };
}

export interface DoneFrame {
  type: 'done';
  data: { session_id: string; message_id: string };
}

export type Frame = TextFrame | ErrorFrame | DoneFrame;