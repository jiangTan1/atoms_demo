// 对话工作区：把会话、对话流、预览与各弹层编排在一起，并承载既有的全部交互语义。

import { useCallback, useEffect, useRef, useState } from 'react';

import { App, theme } from 'antd';

import { ApiError, requestBlob } from '../../api/client';
import { toChatMessages, useChatStream, type TurnResult } from '../../hooks/useChatStream';
import { useAuth } from '../../hooks/useAuth';
import { usePreview } from '../../hooks/usePreview';
import { readStoredSession, useSessions } from '../../hooks/useSessions';
import { saveBlob } from '../../utils';
import Composer from '../chat/Composer';
import MessageList from '../chat/MessageList';
import ExamplesDialog from '../dialogs/ExamplesDialog';
import PasswordDialog from '../dialogs/PasswordDialog';
import ShareDialog from '../dialogs/ShareDialog';
import VersionsDialog from '../dialogs/VersionsDialog';
import PreviewPanel from '../preview/PreviewPanel';
import AppShell from './AppShell';
import SiderNav from './SiderNav';

interface Dialogs {
  password: boolean;
  versions: boolean;
  share: boolean;
  examples: boolean;
}

export default function Workspace() {
  const { identity, logout } = useAuth();
  const { message } = App.useApp();
  const { token } = theme.useToken();

  const sessions = useSessions();
  const preview = usePreview();
  const { refresh: refreshPreview } = preview;

  const [input, setInput] = useState('');
  const [status, setStatus] = useState('');
  const [dialogs, setDialogs] = useState<Dialogs>({
    password: false,
    versions: false,
    share: false,
    examples: false,
  });

  // 供回调读取「当前」会话，避免闭包里的旧值
  const sessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    sessionIdRef.current = sessions.sessionId;
  }, [sessions.sessionId]);

  const handleTurnEnd = useCallback(
    async (result: TurnResult, createdSessionId: string | null) => {
      const changed = !!createdSessionId && createdSessionId !== sessionIdRef.current;
      if (createdSessionId) sessions.setSessionId(createdSessionId);
      if (result === 'done') await sessions.refreshList();
      setStatus(result === 'interrupted' ? '本轮未完成，已写入沙箱的部分内容仍保留。' : '');
      // 失败不刷新预览；会话已切换时由下面的 effect 负责刷新
      if (!changed && result !== 'error') {
        await refreshPreview(createdSessionId ?? sessionIdRef.current);
      }
    },
    [sessions, refreshPreview],
  );

  const chat = useChatStream({ sessionId: sessions.sessionId, onTurnEnd: handleTurnEnd });

  // 会话变化即刷新预览（含切换会话、新建、示例应用）
  useEffect(() => {
    void refreshPreview(sessions.sessionId);
  }, [sessions.sessionId, refreshPreview]);

  // 页面加载：恢复上次会话的历史，再拉取历史会话列表
  const bootstrapped = useRef(false);
  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    (async () => {
      const stored = readStoredSession();
      if (stored) {
        const result = await sessions.loadMessages(stored);
        if (result.status === 'ok') {
          sessions.setSessionId(stored);
          chat.setMessages(toChatMessages(result.messages));
        } else if (result.status === 'missing') {
          sessions.setSessionId(null);
        } else {
          return; // 载入失败：保持新会话，不打断使用者
        }
      }
      await sessions.refreshList();
    })();
    // 仅在挂载时执行一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleNewSession = useCallback(() => {
    chat.reset();
    sessions.setSessionId(null);
    setInput('');
    setStatus('已新建会话');
  }, [chat, sessions]);

  const handleSwitchSession = useCallback(
    async (id: string) => {
      if (chat.streaming) {
        message.warning('正在生成回复，请稍候再切换会话');
        return;
      }
      if (id === sessionIdRef.current) return;
      const result = await sessions.loadMessages(id);
      if (result.status === 'ok') {
        sessions.setSessionId(id);
        chat.setMessages(toChatMessages(result.messages));
        setStatus('已切换到历史会话');
      } else if (result.status === 'missing') {
        sessions.setSessionId(null);
        chat.reset();
        setStatus('该会话已不存在，已切到新会话');
      } else {
        setStatus('历史会话载入失败，请稍后重试');
        return;
      }
      await sessions.refreshList();
    },
    [chat, sessions, message],
  );

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || chat.streaming) return;
    setInput('');
    setStatus('');
    await chat.send(text);
  }, [input, chat]);

  const handleDownload = useCallback(async () => {
    if (chat.streaming) {
      setStatus('正在生成回复，请稍候再下载');
      return;
    }
    const id = sessionIdRef.current;
    if (!id) {
      setStatus('还没有会话与生成的文件，先让助手生成一个项目再下载');
      return;
    }
    setStatus('正在打包…');
    try {
      const { blob, filename } = await requestBlob(
        `/api/workspace/download?session_id=${encodeURIComponent(id)}`,
        `workspace-${id.slice(0, 8)}.zip`,
      );
      saveBlob(blob, filename);
      setStatus('已下载当前会话生成的全部文件');
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail || err.message : (err as Error).message;
      setStatus(`下载失败：${detail}`);
    }
  }, [chat.streaming]);

  const handleExampleApplied = useCallback(
    async (id: string, text: string) => {
      setDialogs((prev) => ({ ...prev, examples: false }));
      chat.reset();
      sessions.setSessionId(id);
      await sessions.refreshList();
      setStatus(text);
    },
    [chat, sessions],
  );

  const handleVersionsChanged = useCallback(
    (text: string) => {
      setStatus(text);
      void refreshPreview(sessionIdRef.current);
    },
    [refreshPreview],
  );

  const openVersions = () => {
    if (!sessionIdRef.current) {
      setStatus('还没有会话，先在对话中生成应用再查看版本');
      return;
    }
    setDialogs((prev) => ({ ...prev, versions: true }));
  };

  const openShare = () => {
    if (!sessionIdRef.current) {
      setStatus('还没有会话，先在对话中生成应用再分享');
      return;
    }
    setDialogs((prev) => ({ ...prev, share: true }));
  };

  const openExamples = () => {
    if (chat.streaming) {
      setStatus('正在生成回复，请稍候再选择示例');
      return;
    }
    setDialogs((prev) => ({ ...prev, examples: true }));
  };

  const nav = (
    <SiderNav
      identity={identity}
      sessions={sessions.sessions}
      activeSessionId={sessions.sessionId}
      onNewSession={handleNewSession}
      onOpenExamples={openExamples}
      onOpenVersions={openVersions}
      onOpenShare={openShare}
      onDownload={handleDownload}
      onSwitchSession={handleSwitchSession}
      onRefreshList={() => void sessions.refreshList()}
      onChangePassword={() => setDialogs((prev) => ({ ...prev, password: true }))}
      onLogout={() => void logout()}
    />
  );

  return (
    <>
      <AppShell sessionId={sessions.sessionId} nav={nav}>
        <div className="workspace-body" style={{ color: token.colorText }}>
          <div className="chat-panel">
            <MessageList messages={chat.messages} onRetry={(id) => void chat.retry(id)} />
            <Composer
              value={input}
              onChange={setInput}
              onSend={() => void handleSend()}
              onInterrupt={chat.interrupt}
              streaming={chat.streaming}
              status={chat.streaming ? chat.progress : status}
            />
          </div>
          <PreviewPanel preview={preview} onRefresh={() => void refreshPreview(sessions.sessionId)} />
        </div>
      </AppShell>

      <PasswordDialog
        open={dialogs.password}
        onClose={() => setDialogs((prev) => ({ ...prev, password: false }))}
        onSuccess={setStatus}
      />
      <VersionsDialog
        open={dialogs.versions}
        sessionId={sessions.sessionId}
        onClose={() => setDialogs((prev) => ({ ...prev, versions: false }))}
        onChanged={handleVersionsChanged}
      />
      <ShareDialog
        open={dialogs.share}
        sessionId={sessions.sessionId}
        onClose={() => setDialogs((prev) => ({ ...prev, share: false }))}
      />
      <ExamplesDialog
        open={dialogs.examples}
        onClose={() => setDialogs((prev) => ({ ...prev, examples: false }))}
        onApplied={handleExampleApplied}
      />
    </>
  );
}