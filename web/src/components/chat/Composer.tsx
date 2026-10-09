import { Button, Input, Space, Typography } from 'antd';

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onInterrupt: () => void;
  streaming: boolean;
  status: string;
}

export default function Composer({
  value,
  onChange,
  onSend,
  onInterrupt,
  streaming,
  status,
}: Props) {
  return (
    <div className="composer">
      <Input.TextArea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={3}
        placeholder="描述你想要的网页应用，Ctrl + Enter 发送"
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            onSend();
          }
        }}
      />
      <div className="composer-actions">
        <Typography.Text type="secondary" className="composer-status">
          {status}
        </Typography.Text>
        <Space>
          {streaming ? (
            <Button danger onClick={onInterrupt} title="取消本轮长任务，已写入沙箱的内容会保留">
              中断
            </Button>
          ) : null}
          <Button type="primary" onClick={onSend} disabled={streaming}>
            发送
          </Button>
        </Space>
      </div>
    </div>
  );
}