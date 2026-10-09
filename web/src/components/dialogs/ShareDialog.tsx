import { useCallback, useEffect, useState } from 'react';

import { App, Button, List, Modal, Select, Space, Typography } from 'antd';

import { ApiError, request } from '../../api/client';
import type {
  ShareCreateResponse,
  ShareItem,
  ShareListResponse,
  ShareRevokeResponse,
  VersionItem,
  VersionListResponse,
} from '../../types';
import { absoluteUrl, copyText, formatTime } from '../../utils';

interface Props {
  open: boolean;
  sessionId: string | null;
  onClose: () => void;
}

export default function ShareDialog({ open, sessionId, onClose }: Props) {
  const { message, modal } = App.useApp();
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [shares, setShares] = useState<ShareItem[]>([]);
  const [versionId, setVersionId] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  const loadShares = useCallback(async () => {
    if (!sessionId) return;
    try {
      const payload = await request<ShareListResponse>(
        'GET',
        `/api/sessions/${encodeURIComponent(sessionId)}/shares`,
      );
      setShares(payload.shares ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onClose();
        return;
      }
      message.error(err instanceof ApiError ? err.detail || err.message : '分享列表载入失败');
    }
  }, [sessionId, message, onClose]);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const payload = await request<VersionListResponse>(
        'GET',
        `/api/sessions/${encodeURIComponent(sessionId)}/versions`,
      );
      const list = payload.versions ?? [];
      setVersions(list);
      setVersionId(list[0]?.version_id);
      await loadShares();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onClose();
        return;
      }
      message.error(err instanceof ApiError ? err.detail || err.message : '版本列表载入失败');
    } finally {
      setLoading(false);
    }
  }, [sessionId, message, onClose, loadShares]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const create = async () => {
    if (!sessionId || !versionId) {
      message.warning('请先选择一个版本。');
      return;
    }
    setCreating(true);
    try {
      const result = await request<ShareCreateResponse>(
        'POST',
        `/api/sessions/${encodeURIComponent(sessionId)}/shares`,
        { version_id: versionId },
      );
      const link = absoluteUrl(result.share.url);
      const copied = await copyText(link);
      const base = result.message || '已生成分享链接。';
      message.success(copied ? `${base}（链接已复制）` : `${base} 链接：${link}`);
      await loadShares();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onClose();
        return;
      }
      message.error(err instanceof ApiError ? err.detail || err.message : '生成分享链接失败');
    } finally {
      setCreating(false);
    }
  };

  const revoke = (token: string) => {
    modal.confirm({
      title: '确认撤销该分享链接？',
      content: '撤销后原链接立即失效。',
      okText: '确认撤销',
      cancelText: '取消',
      onOk: async () => {
        setRevoking(token);
        try {
          const result = await request<ShareRevokeResponse>(
            'DELETE',
            `/api/shares/${encodeURIComponent(token)}`,
          );
          message.success(result.message || '已撤销该分享链接。');
          await loadShares();
        } catch (err) {
          if (err instanceof ApiError && err.status === 401) {
            onClose();
            return;
          }
          message.error(err instanceof ApiError ? err.detail || err.message : '撤销分享失败');
        } finally {
          setRevoking(null);
        }
      },
    });
  };

  const copyLink = async (url: string) => {
    const ok = await copyText(absoluteUrl(url));
    message[ok ? 'success' : 'error'](ok ? '链接已复制' : '复制失败');
  };

  return (
    <Modal
      title="分享应用"
      open={open}
      onCancel={onClose}
      width={560}
      footer={<Button onClick={onClose}>关闭</Button>}
    >
      <Typography.Paragraph type="secondary">
        为选中的版本生成公开只读链接：任何人无需登录即可打开该版本的应用，但不能修改、下载或看到会话信息。
      </Typography.Paragraph>
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Select
          style={{ flex: 1 }}
          value={versionId}
          onChange={setVersionId}
          placeholder={versions.length ? '选择版本' : '暂无可分享的版本'}
          loading={loading}
          options={versions.map((item, index) => ({
            value: item.version_id,
            label: `版本 ${item.version_id}${index === 0 ? '（最新）' : ''}${
              formatTime(item.created_at) ? ` · ${formatTime(item.created_at)}` : ''
            }`,
          }))}
        />
        <Button type="primary" onClick={create} loading={creating} disabled={!versionId}>
          生成分享链接
        </Button>
      </Space.Compact>
      {!versions.length && !loading ? (
        <Typography.Paragraph type="secondary">
          还没有版本：智能体改动沙箱内容后会自动留档，之后即可分享。
        </Typography.Paragraph>
      ) : null}
      <List
        dataSource={shares}
        locale={{ emptyText: '还没有为该会话创建过分享。' }}
        renderItem={(item) => (
          <List.Item
            actions={[
              <Button key="copy" size="small" onClick={() => copyLink(item.url)}>
                复制
              </Button>,
              <Button
                key="revoke"
                size="small"
                danger
                loading={revoking === item.token}
                onClick={() => revoke(item.token)}
              >
                撤销
              </Button>,
            ]}
          >
            <List.Item.Meta
              title={`版本 ${item.version_id}`}
              description={
                <Typography.Text type="secondary" ellipsis={{ tooltip: absoluteUrl(item.url) }}>
                  {absoluteUrl(item.url)}
                </Typography.Text>
              }
            />
          </List.Item>
        )}
      />
    </Modal>
  );
}