import { useEffect, useRef } from 'react';

import { Typography } from 'antd';

import type { ChatMessage } from '../../hooks/useChatStream';
import MessageBubble from './MessageBubble';

interface Props {
  messages: ChatMessage[];
  onRetry: (messageId: string) => void;
}

function EmptyHint() {
  return (
    <div className="empty-hint">
      <Typography.Paragraph>
        描述你想要的网页应用，智能体会生成可运行的文件并在这里预览。
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary">
        示例：做一个俄罗斯方块小游戏；做一个能算账的记账页面；给这个应用加一个计分板。
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary">
        想立刻看到成品？点侧边栏的「示例应用」，选一个内置小游戏或小工具即可。
      </Typography.Paragraph>
    </div>
  );
}

export default function MessageList({ messages, onRetry }: Props) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = listRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages]);

  return (
    <div className="message-list" ref={listRef}>
      {messages.length === 0 ? (
        <EmptyHint />
      ) : (
        messages.map((message) => (
          <MessageBubble key={message.id} message={message} onRetry={onRetry} />
        ))
      )}
    </div>
  );
}