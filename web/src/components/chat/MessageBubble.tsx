import type { CSSProperties } from 'react';

import { Button } from 'antd';

import type { ChatMessage } from '../../hooks/useChatStream';
import MarkdownView from '../markdown/MarkdownView';

interface Props {
  message: ChatMessage;
  onRetry: (messageId: string) => void;
}

export default function MessageBubble({ message, onRetry }: Props) {
  const isUser = message.role === 'user';
  const bubbleStyle: CSSProperties = isUser
    ? { background: 'var(--bubble-user-bg)' }
    : { background: 'var(--bubble-assistant-bg)' };

  return (
    <div className={`message ${isUser ? 'user' : 'assistant'}`}>
      <span className="role">{isUser ? '你' : '助手'}</span>
      <div className="bubble" style={bubbleStyle}>
        {isUser ? message.text : <MarkdownView markdown={message.text} />}
      </div>
      {message.error ? (
        <div className="error-tip">
          <span>{message.error}</span>
          {message.retryable ? (
            <Button size="small" onClick={() => onRetry(message.id)}>
              重试
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}