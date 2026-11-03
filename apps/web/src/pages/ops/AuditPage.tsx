import { useQuery } from "@tanstack/react-query";
import { Select, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { AUDIT_FIELD_LABEL, AUDIT_LABEL } from "@/components/labels";
import { PageHead } from "@/components/PageHead";

const LOGIN_METHOD: Record<string, string> = { password: "密码", sms: "验证码", student: "学生账号" };

function detailText(detail: Record<string, unknown>, planNames: Record<string, string>) {
  return Object.entries(detail)
    .map(([k, v]) => {
      let value = v;
      if (k === "method") value = LOGIN_METHOD[String(v)] ?? v;
      if (k === "plan_id" && v) value = planNames[String(v)] ?? v;
      if (k === "expires_at" && v) value = dayjs(String(v)).format("YYYY-MM-DD");
      if (typeof v === "boolean") value = v ? "是" : "否";
      if (v === null) value = "不限";
      return `${AUDIT_FIELD_LABEL[k] ?? k}：${value}`;
    })
    .join("；");
}

export function AuditPage() {
  const [tenantId, setTenantId] = useState<string>();
  const [action, setAction] = useState<string>();
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const tenants = useQuery({ queryKey: ["ops", "tenants"], queryFn: async () => unwrap(await api.GET("/api/ops/tenants")) });
  const plans = useQuery({ queryKey: ["ops", "plans"], queryFn: async () => unwrap(await api.GET("/api/ops/plans")) });
  const planNames = Object.fromEntries((plans.data ?? []).map((p) => [p.id, p.name]));
  const logs = useQuery({
    queryKey: ["ops", "audit", tenantId, action, page],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/ops/audit", { params: { query: { tenant_id: tenantId, action, page, page_size: pageSize } } }),
      ),
  });

  return (
    <>
      <PageHead title="审计日志" />
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          allowClear
          placeholder="全部机构"
          style={{ width: 200 }}
          value={tenantId}
          onChange={(v) => {
            setTenantId(v);
            setPage(1);
          }}
          options={(tenants.data ?? []).map((t) => ({ value: t.id, label: t.name }))}
        />
        <Select
          allowClear
          showSearch={{ optionFilterProp: "label" }}
          placeholder="全部操作"
          style={{ width: 160 }}
          value={action}
          onChange={(v) => {
            setAction(v);
            setPage(1);
          }}
          options={Object.entries(AUDIT_LABEL).map(([value, label]) => ({ value, label }))}
        />
      </Space>
      <Table
        size="small"
        rowKey="id"
        loading={logs.isLoading}
        dataSource={logs.data?.items}
        scroll={{ x: 760 }}
        pagination={{
          current: page,
          pageSize,
          total: logs.data?.total ?? 0,
          onChange: setPage,
          showTotal: (n) => `共 ${n} 条`,
        }}
        columns={[
          { title: "时间", dataIndex: "created_at", width: 150, render: (t) => dayjs(t).format("YYYY-MM-DD HH:mm") },
          { title: "机构", dataIndex: "tenant_name", width: 140, render: (n) => n ?? "平台" },
          { title: "操作人", dataIndex: "actor_name", width: 110, render: (n) => n ?? "—" },
          {
            title: "操作",
            dataIndex: "action",
            width: 110,
            render: (a) => <Tag color={a === "login_failed" ? "red" : undefined}>{AUDIT_LABEL[a] ?? a}</Tag>,
          },
          {
            title: "详情",
            dataIndex: "detail",
            render: (d) =>
              Object.keys(d).length ? (
                <span className="audit-detail">{detailText(d, planNames)}</span>
              ) : (
                <Typography.Text type="secondary">—</Typography.Text>
              ),
          },
        ]}
      />
    </>
  );
}
