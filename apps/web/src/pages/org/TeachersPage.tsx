import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, Modal, Popconfirm, Space, Switch, Table, Tag } from "antd";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { showPassword } from "@/components/showPassword";
import { ToggleActive } from "./ToggleActive";

type UserOut = Schemas["UserOut"];
type TeacherIn = Schemas["TeacherIn"];

export function TeachersPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<TeacherIn>();

  const methods = useQuery({ queryKey: ["auth", "methods"], queryFn: async () => unwrap(await api.GET("/api/auth/methods")) });
  const smsEnabled = methods.data?.sms ?? true;
  const teachers = useQuery({
    queryKey: ["org", "teachers"],
    queryFn: async () => unwrap(await api.GET("/api/org/teachers")),
  });

  const create = useMutation({
    mutationFn: async (v: TeacherIn) => unwrap(await api.POST("/api/org/teachers", { body: { ...v, password: v.password || null } })),
    onSuccess: () => {
      message.success("已添加老师");
      qc.invalidateQueries({ queryKey: ["org", "teachers"] });
      setOpen(false);
    },
    onError: (e) => message.error(e.message),
  });

  const reset = useMutation({
    mutationFn: async (u: UserOut) =>
      unwrap(await api.POST("/api/org/users/{user_id}/reset-password", { params: { path: { user_id: u.id } } })),
    onSuccess: (r, u) => showPassword(modal, "密码已重置", u.name, r.password),
    onError: (e) => message.error(e.message),
  });

  return (
    <>
      <PageHead
        title="老师"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            添加老师
          </Button>
        }
      />
      <Table
        rowKey="id"
        loading={teachers.isLoading}
        dataSource={teachers.data}
        scroll={{ x: 560 }}
        columns={[
          { title: "姓名", dataIndex: "name" },
          { title: "手机号", dataIndex: "phone_masked" },
          {
            title: "身份",
            render: (_, u) => (
              <>
                <Tag>老师</Tag>
                {u.roles.includes("org_admin") && <Tag color="gold">管理员</Tag>}
              </>
            ),
          },
          { title: "状态", render: (_, u) => (u.active ? <Tag color="green">正常</Tag> : <Tag>停用</Tag>) },
          {
            title: "操作",
            width: 160,
            render: (_, u) =>
              u.roles.includes("org_admin") ? null : (
                <Space size={0}>
                  <Popconfirm title={`重置 ${u.name} 的密码？`} onConfirm={() => reset.mutate(u)}>
                    <Button type="link" size="small">
                      重置密码
                    </Button>
                  </Popconfirm>
                  <ToggleActive user={u} />
                </Space>
              ),
          },
        ]}
      />
      <Modal
        title="添加老师"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(v) => create.mutate(v)} initialValues={{ is_org_admin: false }}>
          <Form.Item name="name" label="姓名" rules={[{ required: true, message: "请输入姓名" }]}>
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item
            name="phone"
            label="手机号"
            extra="老师用手机号登录"
            rules={[
              { required: true, message: "请输入手机号" },
              { pattern: /^1\d{10}$/, message: "手机号格式不正确" },
            ]}
          >
            <Input inputMode="tel" />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            extra={smsEnabled ? "可不填，老师可以用手机验证码登录" : "还没有开通短信登录，老师只能用密码登录"}
            rules={[{ required: !smsEnabled, message: "请设置初始密码" }, { min: 6, message: "至少 6 位" }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="is_org_admin" label="同时设为机构管理员" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
