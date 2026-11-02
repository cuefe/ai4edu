import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, Modal, Radio, Table, Tag } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { PageHead } from "@/components/PageHead";

type TenantIn = Schemas["TenantIn"];

export function TenantsPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<TenantIn>();

  const tenants = useQuery({ queryKey: ["ops", "tenants"], queryFn: async () => unwrap(await api.GET("/api/ops/tenants")) });
  const create = useMutation({
    mutationFn: async (v: TenantIn) =>
      unwrap(await api.POST("/api/ops/tenants", { body: { ...v, admin_password: v.admin_password || null } })),
    onSuccess: () => {
      message.success("机构已开通");
      qc.invalidateQueries({ queryKey: ["ops", "tenants"] });
      setOpen(false);
    },
    onError: (e) => message.error(e.message),
  });

  return (
    <>
      <PageHead
        title="机构管理"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            开通机构
          </Button>
        }
      />
      <Table
        rowKey="id"
        loading={tenants.isLoading}
        dataSource={tenants.data}
        scroll={{ x: 640 }}
        columns={[
          { title: "机构", dataIndex: "name" },
          { title: "代码", dataIndex: "code", render: (c) => <Tag>{c}</Tag> },
          { title: "类型", dataIndex: "kind", render: (k) => (k === "school" ? "学校" : "教培机构") },
          { title: "账号数", dataIndex: "user_count", width: 90 },
          { title: "状态", dataIndex: "active", render: (a) => (a ? <Tag color="green">正常</Tag> : <Tag>停用</Tag>) },
          { title: "开通时间", dataIndex: "created_at", render: (t) => dayjs(t).format("YYYY-MM-DD") },
        ]}
      />
      <Modal
        title="开通机构"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" initialValues={{ kind: "school" }} onFinish={(v) => create.mutate(v)}>
          <Form.Item name="name" label="机构名称" rules={[{ required: true, message: "请输入机构名称" }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item
            name="code"
            label="机构代码"
            extra="学生登录时填写，建议用拼音缩写，开通后不能修改"
            rules={[
              { required: true, message: "请输入机构代码" },
              { pattern: /^[A-Za-z0-9_-]{2,32}$/, message: "2–32 位字母、数字、下划线或减号" },
            ]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="kind" label="类型">
            <Radio.Group
              options={[
                { value: "school", label: "学校" },
                { value: "institution", label: "教培机构" },
              ]}
            />
          </Form.Item>
          <Form.Item name="admin_name" label="管理员姓名" rules={[{ required: true, message: "请输入管理员姓名" }]}>
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item
            name="admin_phone"
            label="管理员手机号"
            rules={[
              { required: true, message: "请输入手机号" },
              { pattern: /^1\d{10}$/, message: "手机号格式不正确" },
            ]}
          >
            <Input inputMode="tel" />
          </Form.Item>
          <Form.Item name="admin_password" label="管理员初始密码" extra="可不填，管理员用手机验证码登录" rules={[{ min: 6, message: "至少 6 位" }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
