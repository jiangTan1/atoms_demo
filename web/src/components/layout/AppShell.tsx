// 应用外壳：antd Layout + 侧边栏 + 顶栏。宽屏用 Sider 承载导航，窄屏收起并改用 Drawer；
// 顶栏保留品牌、会话 ID（始终可见）与主题切换（见 design.md 决策 4）。

import { useEffect, useState, type ReactNode } from 'react';

import { Button, Drawer, Layout, theme, Typography } from 'antd';

import { useTheme } from '../../hooks/useTheme';
import { THEME_LABELS } from '../../theme';

const { Header, Sider, Content } = Layout;

const NARROW_QUERY = '(max-width: 991px)';

function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW_QUERY).matches);
  useEffect(() => {
    const query = window.matchMedia(NARROW_QUERY);
    const onChange = () => setNarrow(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  return narrow;
}

interface Props {
  sessionId: string | null;
  nav: ReactNode;
  children: ReactNode;
}

export default function AppShell({ sessionId, nav, children }: Props) {
  const { token } = theme.useToken();
  const { mode, cycle } = useTheme();
  const isNarrow = useIsNarrow();
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <Layout style={{ height: '100vh' }}>
      {!isNarrow ? (
        <Sider
          width={280}
          theme="light"
          style={{ borderRight: `1px solid ${token.colorBorderSecondary}`, overflow: 'hidden' }}
        >
          {nav}
        </Sider>
      ) : null}

      <Layout>
        <Header
          style={{
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            padding: '0 12px',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            lineHeight: 'normal',
          }}
        >
          {isNarrow ? <Button onClick={() => setDrawerOpen(true)}>菜单</Button> : null}
          <span className="brand-title">网页应用生成智能体</span>
          <Typography.Text
            className="session-chip"
            title={sessionId ? `当前会话 ID：${sessionId}` : '当前还没有会话 ID'}
            style={{
              background: token.colorFillTertiary,
              borderRadius: 6,
              padding: '2px 8px',
              fontSize: 12,
              maxWidth: '46vw',
            }}
            ellipsis
          >
            会话 ID：{sessionId || '新会话（尚未创建）'}
          </Typography.Text>
          <div style={{ flex: 1 }} />
          <Button onClick={cycle} title="切换界面主题：自动 / 浅色 / 深色">
            主题：{THEME_LABELS[mode]}
          </Button>
        </Header>

        <Content style={{ padding: 16, minHeight: 0, overflow: 'hidden' }}>{children}</Content>
      </Layout>

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        placement="left"
        width={300}
        styles={{ body: { padding: 0 } }}
      >
        {/* 窄屏下点任一入口后自动收起抽屉 */}
        <div onClickCapture={() => setDrawerOpen(false)}>{nav}</div>
      </Drawer>
    </Layout>
  );
}