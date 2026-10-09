import { useCallback, useEffect, useState } from 'react';

import { App, Button, List, Modal, Typography } from 'antd';

import { ApiError, request } from '../../api/client';
import type { ExampleApplyResponse, ExampleItem, ExampleListResponse } from '../../types';

interface Props {
  open: boolean;
  onClose: () => void;
  onApplied: (sessionId: string, message: string) => void;
}

export default function ExamplesDialog({ open, onClose, onApplied }: Props) {
  const { message } = App.useApp();
  const [examples, setExamples] = useState<ExampleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await request<ExampleListResponse>('GET', '/api/examples');
      setExamples(payload.examples ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onClose();
        return;
      }
      message.error(err instanceof ApiError ? err.detail || err.message : '示例列表载入失败');
    } finally {
      setLoading(false);
    }
  }, [message, onClose]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const apply = async (example: ExampleItem) => {
    setApplying(example.id);
    try {
      const result = await request<ExampleApplyResponse>('POST', '/api/examples/apply', {
        example_id: example.id,
      });
      onApplied(result.session_id, result.message || '已创建示例应用，可直接预览。');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onClose();
        return;
      }
      message.error(err instanceof ApiError ? err.detail || err.message : '示例创建失败');
    } finally {
      setApplying(null);
    }
  };

  return (
    <Modal
      title="示例应用"
      open={open}
      onCancel={onClose}
      width={600}
      footer={<Button onClick={onClose}>关闭</Button>}
    >
      <Typography.Paragraph type="secondary">
        选择一个内置示例：系统会为它新建一个会话并把示例文件写入沙箱，无需等待生成即可预览，
        之后也能继续对话修改、留版本与分享。
      </Typography.Paragraph>
      <List
        loading={loading}
        dataSource={examples}
        locale={{ emptyText: '暂无可用的内置示例。' }}
        renderItem={(item) => (
          <List.Item
            actions={[
              <Button
                key="use"
                type="primary"
                size="small"
                loading={applying === item.id}
                onClick={() => apply(item)}
              >
                使用
              </Button>,
            ]}
          >
            <List.Item.Meta title={item.name} description={item.description} />
          </List.Item>
        )}
      />
    </Modal>
  );
}