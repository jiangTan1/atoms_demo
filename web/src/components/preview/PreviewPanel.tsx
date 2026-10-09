import { Button, Typography } from 'antd';

import type { PreviewApi } from '../../hooks/usePreview';

interface Props {
  preview: PreviewApi;
  onRefresh: () => void;
}

export default function PreviewPanel({ preview, onRefresh }: Props) {
  return (
    <div className="preview-panel">
      <div className="preview-head">
        <Typography.Text strong>应用预览</Typography.Text>
        <Typography.Text type="secondary" className="preview-state">
          {preview.stateText}
        </Typography.Text>
        <Button size="small" onClick={onRefresh}>
          刷新
        </Button>
      </div>
      <div className="preview-body">
        {preview.url ? (
          <iframe
            key={preview.url}
            className="preview-frame"
            src={preview.url}
            sandbox="allow-scripts allow-forms allow-modals allow-popups allow-pointer-lock"
            referrerPolicy="no-referrer"
            title="当前会话应用的预览"
          />
        ) : (
          <div className="preview-placeholder">
            <Typography.Paragraph>{preview.placeholder}</Typography.Paragraph>
          </div>
        )}
      </div>
    </div>
  );
}