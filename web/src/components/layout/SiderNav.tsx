// 侧边栏导航：新建会话、功能入口、历史会话列表与用户区（见 design.md 决策 4）。

import { Button, Divider, Typography } from 'antd';

import type { Identity, SessionSummary } from '../../types';
import { formatTime } from '../../utils';

interface Props {
  identity: Identity | null;
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onNewSession: () => void;
  onOpenExamples: () => void;
  onOpenVersions: () => void;
  onOpenShare: () => void;
  onDownload: () => void;
  onSwitchSession: (sessionId: string) => void;
  onRefreshList: () => void;
  onChangePassword: () => void;
  onLogout: () => void;
}

export default function SiderNav({
  identity,
  sessions,
  activeSessionId,
  onNewSession,
  onOpenExamples,
  onOpenVersions,
  onOpenShare,
  onDownload,
  onSwitchSession,
  onRefreshList,
  onChangePassword,
  onLogout,
}: Props) {
  const roleText = identity?.role === 'admin' ? '（管理员）' : '';

  return (
    <div className="sider-nav">
      <Button type="primary" block onClick={onNewSession}>
        新建会话
      </Button>

      <div className="nav-actions">
        <Button type="text" block className="nav-item" onClick={onOpenExamples}>
          示例应用
        </Button>
        <Button type="text" block className="nav-item" onClick={onOpenVersions}>
          版本
        </Button>
        <Button type="text" block className="nav-item" onClick={onOpenShare}>
          分享
        </Button>
        <Button type="text" block className="nav-item" onClick={onDownload}>
          下载整个项目
        </Button>
      </div>

      <Divider style={{ margin: '4px 0' }} />

      <div className="nav-section-head">
        <Typography.Text strong>历史会话</Typography.Text>
        <Button type="link" size="small" onClick={onRefreshList}>
          刷新
        </Button>
      </div>

      <div className="history-list">
        {sessions.length === 0 ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            暂无历史会话
          </Typography.Text>
        ) : (
          sessions.map((item) => {
            const time = formatTime(item.updated_at);
            return (
              <button
                key={item.session_id}
                type="button"
                className={`history-item${item.session_id === activeSessionId ? ' active' : ''}`}
                onClick={() => onSwitchSession(item.session_id)}
              >
                <span className="history-title">{item.title || '（空会话）'}</span>
                <span className="history-meta">
                  {time ? `${time} · ${item.message_count} 条消息` : `${item.message_count} 条消息`}
                </span>
              </button>
            );
          })
        )}
      </div>

      <Divider style={{ margin: '4px 0' }} />

      <div className="nav-user">
        <Typography.Text type="secondary" ellipsis title={identity ? `当前登录用户：${identity.username}${roleText}` : '当前登录用户'}>
          当前用户：{identity ? `${identity.username}${roleText}` : '—'}
        </Typography.Text>
        <Button type="text" block className="nav-item" onClick={onChangePassword}>
          修改密码
        </Button>
        <Button type="text" block className="nav-item" danger onClick={onLogout}>
          退出登录
        </Button>
      </div>
    </div>
  );
}