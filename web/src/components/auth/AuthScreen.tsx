// 认证界面：登录 / 注册两种表单，以及「修改密码」的入口提示（未登录不允许改密）。
// 未登录（或登录态失效）时这是唯一的界面（见 design.md 决策 11 与既有语义）。

import { useState } from 'react';

import { Button, Card, Divider, Form, Input, Segmented, Space, Typography } from 'antd';

import { ApiError } from '../../api/client';
import { useAuth } from '../../hooks/useAuth';

const CHANGE_PASSWORD_HINT = '修改密码需要先登录：登录后可在对话界面侧边栏的「修改密码」中修改。';
const BAD_CREDENTIALS_TIP = '用户名或密码错误。';

type Mode = 'login' | 'register';

interface FormValues {
  username: string;
  password: string;
}

export default function AuthScreen() {
  const { login, register, notice, setNotice } = useAuth();
  const [mode, setMode] = useState<Mode>('login');
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const switchMode = (next: Mode) => {
    setMode(next);
    setNotice('');
    form.resetFields();
  };

  const submit = async (values: FormValues) => {
    setSubmitting(true);
    setNotice('');
    try {
      if (mode === 'register') {
        const text = await register(values.username, values.password);
        setMode('login');
        form.resetFields();
        setNotice(text);
        return;
      }
      await login(values.username, values.password);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setNotice(BAD_CREDENTIALS_TIP);
        return;
      }
      setNotice(err instanceof ApiError ? err.detail || err.message : (err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-screen">
      <Card className="auth-card" style={{ width: 400 }}>
        <Typography.Title level={4} style={{ marginBottom: 4 }}>
          网页应用生成智能体
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          对话生成网页应用 · 即时预览 · 版本回滚 · 分享
        </Typography.Paragraph>

        <Segmented
          block
          value={mode}
          onChange={(value) => switchMode(value as Mode)}
          options={[
            { label: '登录', value: 'login' },
            { label: '注册', value: 'register' },
          ]}
        />

        <Form form={form} layout="vertical" onFinish={submit} style={{ marginTop: 16 }}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请填写用户名。' },
              { min: 3, max: 20, message: '用户名长度需为 3 到 20 个字符。' },
            ]}
          >
            <Input autoComplete="username" maxLength={20} placeholder="3 到 20 个字符" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[
              { required: true, message: '请填写密码。' },
              { min: 3, max: 20, message: '密码长度需为 3 到 20 个字符。' },
            ]}
          >
            <Input.Password
              autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
              maxLength={20}
            />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={submitting}>
              {mode === 'register' ? '注册' : '登录'}
            </Button>
            <Button onClick={() => switchMode('login')}>取消</Button>
          </Space>
        </Form>

        <Divider plain style={{ margin: '16px 0 8px' }}>
          其他操作
        </Divider>
        <Button type="link" size="small" style={{ paddingLeft: 0 }} onClick={() => setNotice(CHANGE_PASSWORD_HINT)}>
          修改密码
        </Button>

        {notice ? (
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }} role="status">
            {notice}
          </Typography.Paragraph>
        ) : null}
      </Card>
    </div>
  );
}