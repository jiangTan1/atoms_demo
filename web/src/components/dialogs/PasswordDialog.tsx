import { useEffect } from 'react';

import { App, Form, Input, Modal, Typography } from 'antd';

import { ApiError } from '../../api/client';
import { useAuth } from '../../hooks/useAuth';

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: (message: string) => void;
}

interface FormValues {
  oldPassword: string;
  newPassword: string;
}

export default function PasswordDialog({ open, onClose, onSuccess }: Props) {
  const { identity, changePassword } = useAuth();
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();

  useEffect(() => {
    if (open) form.resetFields();
  }, [open, form]);

  const roleText = identity?.role === 'admin' ? '（管理员）' : '';

  const handleOk = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    try {
      const result = await changePassword(values.oldPassword, values.newPassword);
      onClose();
      onSuccess(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onClose();
        return;
      }
      message.error(err instanceof ApiError ? err.detail || err.message : (err as Error).message);
    }
  };

  return (
    <Modal
      title="修改密码"
      open={open}
      onOk={handleOk}
      onCancel={onClose}
      okText="确认修改"
      cancelText="取消"
      forceRender
    >
      {identity ? (
        <Typography.Paragraph type="secondary">
          将修改账号「{identity.username}
          {roleText}」的密码，其他设备上的登录态会立即失效。
        </Typography.Paragraph>
      ) : null}
      <Form form={form} layout="vertical">
        <Form.Item
          name="oldPassword"
          label="原密码"
          rules={[{ required: true, message: '请填写原密码。' }]}
        >
          <Input.Password autoComplete="current-password" maxLength={20} />
        </Form.Item>
        <Form.Item
          name="newPassword"
          label="新密码"
          rules={[
            { required: true, message: '请填写新密码。' },
            { min: 3, max: 20, message: '密码长度需为 3 到 20 个字符。' },
          ]}
        >
          <Input.Password
            autoComplete="new-password"
            maxLength={20}
            placeholder="3 到 20 个字符"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}