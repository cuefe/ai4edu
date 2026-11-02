import { App, Form, Input, Modal, Typography } from "antd";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";

interface Values {
  old_password: string;
  new_password: string;
  confirm: string;
}

export function ChangePasswordModal({
  open,
  forced,
  onClose,
}: {
  open: boolean;
  forced: boolean;
  onClose: () => void;
}) {
  const { login, logout } = useAuth();
  const { message } = App.useApp();
  const [form] = Form.useForm<Values>();
  const [saving, setSaving] = useState(false);

  async function submit(values: Values) {
    setSaving(true);
    try {
      const t = unwrap(
        await api.POST("/api/me/password", {
          body: { old_password: values.old_password, new_password: values.new_password },
        }),
      );
      login(t);
      message.success("密码已修改");
      form.resetFields();
      onClose();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={forced ? "首次登录，请修改密码" : "修改密码"}
      open={open}
      closable={!forced}
      mask={{ closable: !forced }}
      okText="确认修改"
      cancelText={forced ? "退出登录" : "取消"}
      onCancel={forced ? logout : onClose}
      onOk={() => form.submit()}
      confirmLoading={saving}
      destroyOnHidden
    >
      {forced && (
        <Typography.Paragraph type="secondary">
          你的密码是管理员设置的初始密码，为了账号安全，请先改成自己的密码。
        </Typography.Paragraph>
      )}
      <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
        <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: "请输入原密码" }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="new_password"
          label="新密码"
          rules={[
            { required: true, message: "请输入新密码" },
            { min: 6, message: "至少 6 位" },
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="确认新密码"
          dependencies={["new_password"]}
          rules={[
            { required: true, message: "请再输入一次新密码" },
            ({ getFieldValue }) => ({
              validator: (_, v) =>
                !v || v === getFieldValue("new_password") ? Promise.resolve() : Promise.reject(new Error("两次输入不一致")),
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
