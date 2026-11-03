import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type FormInstance,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { yuan } from "@/components/labels";
import { PageHead } from "@/components/PageHead";
import { expiryTag, QuotaMeter } from "@/components/QuotaMeter";

type TenantOut = Schemas["TenantOut"];
type PlanOut = Schemas["PlanOut"];

interface TermsValues {
  plan_id?: string | null;
  expires_at?: Dayjs | null;
  student_quota?: number | null;
  teacher_quota?: number | null;
  ai_budget_yuan?: number | null;
  note?: string;
}

type CreateValues = TermsValues & Omit<Schemas["TenantIn"], keyof TermsValues>;
type EditValues = TermsValues & { name: string };

function termsBody(v: TermsValues) {
  return {
    plan_id: v.plan_id ?? null,
    // 到期日当天还能用，到当天 23:59:59 为止
    expires_at: v.expires_at ? v.expires_at.endOf("day").toISOString() : null,
    student_quota: v.student_quota ?? null,
    teacher_quota: v.teacher_quota ?? null,
    ai_budget_yuan: v.ai_budget_yuan ?? null,
    note: v.note ?? "",
  };
}


// 开通和编辑共用：选套餐时按套餐带出名额、额度和到期日，之后还能单独改
function TermsFields({ plans, onPlan }: { plans: PlanOut[]; onPlan: (p: PlanOut) => void }) {
  return (
    <>
      <Form.Item name="plan_id" label="套餐">
        <Select
          allowClear
          placeholder="选择套餐，自动带出名额和额度"
          options={plans.filter((p) => p.active).map((p) => ({ value: p.id, label: p.name }))}
          onChange={(id) => {
            const plan = plans.find((p) => p.id === id);
            if (plan) onPlan(plan);
          }}
        />
      </Form.Item>
      <Space wrap size={16}>
        <Form.Item name="student_quota" label="学生名额" extra="不填表示不限">
          <InputNumber min={1} precision={0} style={{ width: 140 }} />
        </Form.Item>
        <Form.Item name="teacher_quota" label="老师名额">
          <InputNumber min={1} precision={0} style={{ width: 140 }} />
        </Form.Item>
        <Form.Item name="ai_budget_yuan" label="每月 AI 额度（元）">
          <InputNumber min={0} precision={2} style={{ width: 160 }} />
        </Form.Item>
      </Space>
      <Form.Item name="expires_at" label="到期日" extra="到期后机构里的账号都不能登录；不填表示不限">
        <DatePicker style={{ width: 200 }} />
      </Form.Item>
      <Form.Item name="note" label="备注">
        <Input.TextArea rows={2} maxLength={500} placeholder="合同编号、联系人等" />
      </Form.Item>
    </>
  );
}

function fillFromPlan<T extends TermsValues>(form: FormInstance<T>, plan: PlanOut) {
  // 续费：没到期的从原到期日往后延，已经到期的从今天算
  const current = (form.getFieldsValue(true) as TermsValues).expires_at;
  const base = current && current.isAfter(dayjs()) ? current : dayjs();
  form.setFieldsValue({
    student_quota: plan.student_quota ?? null,
    teacher_quota: plan.teacher_quota ?? null,
    ai_budget_yuan: plan.ai_budget_yuan == null ? null : Number(plan.ai_budget_yuan),
    expires_at: base.add(plan.months, "month"),
  } as Partial<T>);
}

export function TenantsPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<TenantOut | null>(null);
  const [createForm] = Form.useForm<CreateValues>();
  const [editForm] = Form.useForm<EditValues>();

  const tenants = useQuery({ queryKey: ["ops", "tenants"], queryFn: async () => unwrap(await api.GET("/api/ops/tenants")) });
  const plans = useQuery({ queryKey: ["ops", "plans"], queryFn: async () => unwrap(await api.GET("/api/ops/plans")) });
  const methods = useQuery({ queryKey: ["auth", "methods"], queryFn: async () => unwrap(await api.GET("/api/auth/methods")) });
  const smsEnabled = methods.data?.sms ?? true;
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops"] });

  const create = useMutation({
    mutationFn: async (v: CreateValues) =>
      unwrap(
        await api.POST("/api/ops/tenants", {
          body: { ...v, ...termsBody(v), admin_password: v.admin_password || null },
        }),
      ),
    onSuccess: () => {
      message.success("机构已开通");
      refresh();
      setCreateOpen(false);
    },
    onError: (e) => message.error(e.message),
  });

  const update = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: Schemas["TenantPatch"] }) =>
      unwrap(await api.PATCH("/api/ops/tenants/{tenant_id}", { params: { path: { tenant_id: id } }, body })),
    onSuccess: () => {
      message.success("已保存");
      refresh();
      setEditing(null);
    },
    onError: (e) => message.error(e.message),
  });

  function openEdit(t: TenantOut) {
    setEditing(t);
    editForm.setFieldsValue({
      name: t.name,
      plan_id: t.plan_id,
      student_quota: t.student_quota,
      teacher_quota: t.teacher_quota,
      ai_budget_yuan: t.ai_budget_yuan == null ? null : Number(t.ai_budget_yuan),
      expires_at: t.expires_at ? dayjs(t.expires_at) : null,
      note: t.note,
    });
  }

  return (
    <>
      <PageHead
        title="机构管理"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            开通机构
          </Button>
        }
      />
      <Table
        rowKey="id"
        loading={tenants.isLoading}
        dataSource={tenants.data}
        scroll={{ x: 1080 }}
        columns={[
          {
            title: "机构",
            render: (_, t) => (
              <Space orientation="vertical" size={0}>
                <span>
                  {t.name} <Tag>{t.code}</Tag>
                </span>
                {t.note && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {t.note}
                  </Typography.Text>
                )}
              </Space>
            ),
          },
          { title: "套餐", dataIndex: "plan_name", width: 100, render: (n) => n ?? "—" },
          {
            title: "学生",
            width: 140,
            render: (_, t) => <QuotaMeter compact used={t.students} quota={t.student_quota} />,
          },
          {
            title: "老师",
            width: 120,
            render: (_, t) => <QuotaMeter compact used={t.teachers} quota={t.teacher_quota} />,
          },
          {
            title: "本月 AI 费用",
            width: 170,
            render: (_, t) => (
              <QuotaMeter
                compact
                used={Number(t.ai_spend_yuan)}
                quota={t.ai_budget_yuan == null ? null : Number(t.ai_budget_yuan)}
                format={yuan}
              />
            ),
          },
          { title: "到期", dataIndex: "expires_at", width: 170, render: expiryTag },
          {
            title: "状态",
            dataIndex: "active",
            width: 70,
            render: (a) => (a ? <Tag color="green">正常</Tag> : <Tag>停用</Tag>),
          },
          {
            title: "操作",
            width: 120,
            fixed: "right",
            render: (_, t) => (
              <Space size={0}>
                <Button type="link" size="small" onClick={() => openEdit(t)}>
                  编辑
                </Button>
                <Popconfirm
                  title={t.active ? `停用 ${t.name}？` : `启用 ${t.name}？`}
                  description={t.active ? "停用后机构里的账号都不能登录" : undefined}
                  onConfirm={() => update.mutate({ id: t.id, body: { active: !t.active } })}
                >
                  <Button type="link" size="small" danger={t.active}>
                    {t.active ? "停用" : "启用"}
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="开通机构"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={create.isPending}
        width={600}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" initialValues={{ kind: "school" }} onFinish={(v) => create.mutate(v)}>
          <Form.Item name="name" label="机构名称" rules={[{ required: true, message: "请输入机构名称" }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Space wrap size={16} align="start">
            <Form.Item
              name="code"
              label="机构代码"
              extra="学生登录时填写，建议用拼音缩写，开通后不能修改"
              rules={[
                { required: true, message: "请输入机构代码" },
                { pattern: /^[A-Za-z0-9_-]{2,32}$/, message: "2–32 位字母、数字、下划线或减号" },
              ]}
              style={{ maxWidth: 280 }}
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
          </Space>
          <TermsFields plans={plans.data ?? []} onPlan={(p) => fillFromPlan(createForm, p)} />
          <Space wrap size={16} align="start">
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
          </Space>
          <Form.Item
            name="admin_password"
            label="管理员初始密码"
            extra={smsEnabled ? "可不填，管理员用手机验证码登录" : "还没有开通短信登录，管理员只能用密码登录"}
            rules={[{ required: !smsEnabled, message: "请设置初始密码" }, { min: 6, message: "至少 6 位" }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑：${editing?.name ?? ""}`}
        open={Boolean(editing)}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        confirmLoading={update.isPending}
        width={600}
        forceRender
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(v) => editing && update.mutate({ id: editing.id, body: { name: v.name, ...termsBody(v) } })}
        >
          <Form.Item name="name" label="机构名称" rules={[{ required: true, message: "请输入机构名称" }]}>
            <Input maxLength={100} />
          </Form.Item>
          <TermsFields plans={plans.data ?? []} onPlan={(p) => fillFromPlan(editForm, p)} />
        </Form>
      </Modal>
    </>
  );
}
