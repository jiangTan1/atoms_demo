import { useCallback, useEffect, useState } from 'react';

import { App, Button, List, Modal, Typography } from 'antd';

import { ApiError, request } from '../../api/client';
import type { RollbackResponse, VersionItem, VersionListResponse } from '../../types';
import { formatTime } from '../../utils';

interface Props {
  open: boolean;
  sessionId: string | null;
  onClose: () => void;
  onChanged: (message: string) => void;
}

export default function VersionsDialog({ open, sessionId, onClose, onChanged }: Props) {
  const { message, modal } = App.useApp();
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [rolling, setRolling] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const payload = await request<VersionListResponse>(
        'GET',
        `/api/sessions/${encodeURIComponent(sessionId)}/versions`,
      );
      setVersions(payload.versions ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onClose();
        return;
      }
      message.error(err instanceof ApiError ? err.detail || err.message : '版本列表载入失败');
    } finally {
      setLoading(false);
    }
  }, [sessionId, message, onClose]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const rollback = (versionId: string) => {
    if (!sessionId) return;
    modal.confirm({
      title: `确认回滚到版本 ${versionId}？`,
      content: '回滚前的内容会留存为新版本，之后仍可回到回滚前。',
      okText: '确认回滚',
      cancelText: '取消',
      onOk: async () => {
        setRolling(versionId);
        try {
          const result = await request<RollbackResponse>(
            'POST',
            `/api/sessions/${encodeURIComponent(sessionId)}/versions/${encodeURIComponent(
              versionId,
            )}/rollback`,
            {},
          );
          message.success(result.message || '已回滚。');
          onChanged('已回滚到所选版本，预览已刷新');
          await load();
        } catch (err) {
          if (err instanceof ApiError && err.status === 401) {
            onClose();
            return;
          }
          message.error(err instanceof ApiError ? err.detail || err.message : '回滚失败');
        } finally {
          setRolling(null);
        }
      },
    });
  };

  return (
    <Modal
      title="版本历史"
      open={open}
      onCancel={onClose}
      width={560}
      footer={<Button onClick={onClose}>关闭</Button>}
    >
      <Typography.Paragraph type="secondary">
        每轮对话改动沙箱内容后自动留档。回滚前会先把当前内容留存为新版本，因此随时可以回到回滚前。
      </Typography.Paragraph>
      <List
        loading={loading}
        dataSource={versions}
        locale={{ emptyText: '还没有版本：智能体改动了沙箱内容后会自动留档。' }}
        renderItem={(item, index) => (
          <List.Item
            actions={[
              <Button
                key="rollback"
                size="small"
                loading={rolling === item.version_id}
                onClick={() => rollback(item.version_id)}
              >
                回滚到该版本
              </Button>,
            ]}
          >
            <List.Item.Meta
              title={`版本 ${item.version_id}${index === 0 ? '（最新）' : ''}`}
              description={formatTime(item.created_at) || '时间未知'}
            />
          </List.Item>
        )}
      />
    </Modal>
  );
}