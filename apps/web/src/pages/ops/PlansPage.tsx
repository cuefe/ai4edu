import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, InputNumber, Modal, Space, Switch, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { yuan } from "@/components/labels";
import { PageHead } from "@/components/PageHead";

type PlanOut = Schemas["PlanOut"];

interface PlanValues {
  name: string;
  student_quota?: number | null;
  teacher_quota?: number | null;
  ai_budget_yuan?: number | null;
  months: number;
  note?: string;
  active: boolean;
}

const unlimited = (n: number | null | undefined, fmt: (n: number) => string = String) =>
  n == null ? <Typography.Text type="secondary">不限</Typography.Text> : fmt(n);

export function PlansPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [editing, setEditing] = useState<PlanOut | "new" | null>(null);
  const [form] = Form.useForm<PlanValues>();

  const plans = useQuery({ queryKey: ["ops", "plans"], queryFn: async () => unwrap(await api.GET("/api/ops/plans")) });
  const save = useMutation({
    mutationFn: async (v: PlanValues) => {
      const body = {
        ...v,
        student_quota: v.student_quota ?? null,
        teacher_quota: v.teacher_quota ?? null,
        ai_budget_yuan: v.ai_budget_yuan ?? null,
        note: v.note ?? "",
      };
      return editing && editing !== "new"
        ? unwrap(await api.PUT("/api/ops/plans/{plan_id}", { params: { path: { plan_id: editing.id } }, body }))
        : unwrap(await api.POST("/api/ops/plans", { body }));
    },
    onSuccess: () => {
      message.success("已保存");
      qc.invalidateQueries({ queryKey: ["ops", "plans"] });
      setEditing(null);
    },
    onError: (e) => message.error(e.message),
  });

  function open(p: PlanOut | "new") {
    setEditing(p);
    form.resetFields();
    if (p !== "new") {
      form.setFieldsValue({ ...p, ai_budget_yuan: p.ai_budget_yuan == null ? null : Number(p.ai_budget_yuan) });
    }
  }

  return (
    <>
      <PageHead
        title="套餐"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => open("new")}>
            新建套餐
          </Button>
        }
      />
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="开通或续费机构时选套餐，名额、额度和到期日会自动带出，也可以单独改。改套餐只影响之后开通、续费的机构。"
      />
      <Table
        rowKey="id"
        loading={plans.isLoading}
        dataSource={plans.data}
        scroll={{ x: 760 }}
        columns={[
          {
            title: "套餐",
            render: (_, p) => (
              <Space orientation="vertical" size={0}>
                <span>
                  {p.name} {!p.active && <Tag>停售</Tag>}
                </span>
                {p.note && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {p.note}
                  </Typography.Text>
                )}
              </Space>
            ),
          },
          { title: "学生名额", dataIndex: "student_quota", render: (n) => unlimited(n) },
          { title: "老师名额", dataIndex: "teacher_quota", render: (n) => unlimited(n) },
          {
            title: "每月 AI 额度",
            dataIndex: "ai_budget_yuan",
            render: (n) => unlimited(n == null ? null : Number(n), yuan),
          },
          { title: "服务期", dataIndex: "months", render: (m) => `${m} 个月` },
          { title: "使用中的机构", dataIndex: "tenant_count" },
          {
            title: "操作",
            width: 80,
            render: (_, p) => (
              <Button type="link" size="small" onClick={() => open(p)}>
                编辑
              </Button>
            ),
          },
        ]}
      />
      <Modal
        title={editing === "new" ? "新建套餐" : "编辑套餐"}
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={() => form.submit()}
        confirmLoading={save.isPending}
        forceRender
      >
        <Form form={form} layout="vertical" initialValues={{ months: 12, active: true }} onFinish={(v) => save.mutate(v)}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入套餐名称" }]}>
            <Input maxLength={50} placeholder="如：标准版（300 人）" />
          </Form.Item>
          <Space wrap size={16}>
            <Form.Item name="student_quota" label="学生名额" extra="不填表示不限">
              <InputNumber min={1} precision={0} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="teacher_quota" label="老师名额">
              <InputNumber min={1} precision={0} style={{ width: 140 }} />
            </Form.Item>
          </Space>
          <Space wrap size={16}>
            <Form.Item name="ai_budget_yuan" label="每月 AI 额度（元）" extra="按官网原价估算的模型费用">
              <InputNumber min={0} precision={2} style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name="months" label="服务期（月）" rules={[{ required: true }]}>
              <InputNumber min={1} max={60} precision={0} style={{ width: 120 }} />
            </Form.Item>
          </Space>
          <Form.Item name="note" label="说明">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Form.Item name="active" label="在售" valuePropName="checked" extra="停售的套餐不出现在开通选项里">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
