import { LockOutlined, MobileOutlined, SafetyOutlined, TeamOutlined, UserOutlined } from "@ant-design/icons";
import { App, Button, Card, Form, Input, Segmented, Space, Tabs, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { api, unwrap, type TokenOut } from "@/api/client";
import { homePath, useAuth } from "@/auth/AuthProvider";

function useCountdown() {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);
  return [left, setLeft] as const;
}

function StaffLogin({ onDone }: { onDone: (t: TokenOut) => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [mode, setMode] = useState<"password" | "sms">("password");
  // 没开通短信时只有密码登录
  const methods = useQuery({ queryKey: ["auth", "methods"], queryFn: async () => unwrap(await api.GET("/api/auth/methods")) });
  const smsEnabled = methods.data?.sms ?? false;
  const [loading, setLoading] = useState(false);
  const [left, setLeft] = useCountdown();

  async function sendCode() {
    try {
      await form.validateFields(["phone"]);
      unwrap(await api.POST("/api/auth/sms/send", { body: { phone: form.getFieldValue("phone") } }));
      message.success("验证码已发送");
      setLeft(60);
    } catch (e) {
      if (e instanceof Error) message.error(e.message);
    }
  }

  async function submit(v: { phone: string; password?: string; code?: string }) {
    setLoading(true);
    try {
      const t =
        mode === "password" || !smsEnabled
          ? unwrap(await api.POST("/api/auth/login/phone", { body: { phone: v.phone, password: v.password! } }))
          : unwrap(await api.POST("/api/auth/login/sms", { body: { phone: v.phone, code: v.code! } }));
      onDone(t);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Form form={form} size="large" onFinish={submit} requiredMark={false}>
      {smsEnabled && (
        <Form.Item>
          <Segmented
            block
            value={mode}
            onChange={(v) => setMode(v as "password" | "sms")}
            options={[
              { label: "密码登录", value: "password" },
              { label: "验证码登录", value: "sms" },
            ]}
          />
        </Form.Item>
      )}
      <Form.Item
        name="phone"
        rules={[
          { required: true, message: "请输入手机号" },
          { pattern: /^1\d{10}$/, message: "手机号格式不正确" },
        ]}
      >
        <Input prefix={<MobileOutlined />} placeholder="手机号" inputMode="tel" autoComplete="tel" />
      </Form.Item>
      {mode === "password" || !smsEnabled ? (
        <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
          <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
        </Form.Item>
      ) : (
        <Form.Item>
          <Space.Compact block>
            <Form.Item name="code" noStyle rules={[{ required: true, message: "请输入验证码" }]}>
              <Input prefix={<SafetyOutlined />} placeholder="验证码" inputMode="numeric" maxLength={6} />
            </Form.Item>
            <Button onClick={sendCode} disabled={left > 0}>
              {left > 0 ? `${left} 秒后重发` : "获取验证码"}
            </Button>
          </Space.Compact>
        </Form.Item>
      )}
      <Button type="primary" htmlType="submit" block loading={loading}>
        登录
      </Button>
    </Form>
  );
}

function StudentLogin({ onDone }: { onDone: (t: TokenOut) => void }) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);

  async function submit(v: { tenant_code: string; username: string; password: string }) {
    setLoading(true);
    try {
      onDone(unwrap(await api.POST("/api/auth/login/student", { body: v })));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Form size="large" onFinish={submit} requiredMark={false}>
      <Form.Item name="tenant_code" rules={[{ required: true, message: "请输入学校代码" }]}>
        <Input prefix={<TeamOutlined />} placeholder="学校 / 机构代码" autoCapitalize="none" />
      </Form.Item>
      <Form.Item name="username" rules={[{ required: true, message: "请输入学号" }]}>
        <Input prefix={<UserOutlined />} placeholder="学号" autoComplete="username" autoCapitalize="none" />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
        <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block loading={loading}>
        登录
      </Button>
    </Form>
  );
}

export function LoginPage() {
  const { me, login } = useAuth();
  const navigate = useNavigate();
  if (me) return <Navigate to={homePath(me)} replace />;

  function done(t: TokenOut) {
    login(t);
    navigate(homePath(t.user), { replace: true });
  }

  return (
    <div className="login-wrap">
      <Card className="login-card">
        <Typography.Title level={3} style={{ textAlign: "center", marginBottom: 4 }}>
          AI 智教平台
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: "center" }}>
          AI 负责教，老师负责育
        </Typography.Paragraph>
        <Tabs
          centered
          items={[
            { key: "staff", label: "老师 / 管理员", children: <StaffLogin onDone={done} /> },
            { key: "student", label: "学生", children: <StudentLogin onDone={done} /> },
          ]}
        />
      </Card>
    </div>
  );
}
