import { ExclamationCircleFilled, WarningFilled } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Card, Checkbox, Select, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { PageHead } from "@/components/PageHead";

const CATEGORY: Record<string, { label: string; color?: string }> = {
  study: { label: "学习相关" },
  chat: { label: "闲聊", color: "blue" },
  unsafe: { label: "不当内容", color: "volcano" },
};

export function crisisTag(level: string) {
  if (level === "high")
    return (
      <Tag color="red" icon={<WarningFilled />}>
        高风险
      </Tag>
    );
  if (level === "low")
    return (
      <Tag color="orange" icon={<ExclamationCircleFilled />}>
        需要关注
      </Tag>
    );
  return <Typography.Text type="secondary">—</Typography.Text>;
}

export function SafetyPage() {
  const [tenantId, setTenantId] = useState<string>();
  const [category, setCategory] = useState<"study" | "chat" | "unsafe">();
  const [crisisOnly, setCrisisOnly] = useState(false);
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const tenants = useQuery({ queryKey: ["ops", "tenants"], queryFn: async () => unwrap(await api.GET("/api/ops/tenants")) });
  const alerts = useQuery({
    queryKey: ["ops", "alerts", "summary"],
    queryFn: async () => unwrap(await api.GET("/api/ops/alerts/summary")),
  });
  const logs = useQuery({
    queryKey: ["ops", "moderation", tenantId, category, crisisOnly, page],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/ops/moderation", {
          params: { query: { tenant_id: tenantId, category, crisis_only: crisisOnly, page, page_size: pageSize } },
        }),
      ),
  });

  return (
    <Space orientation="vertical" size="large" style={{ width: "100%" }}>
      <PageHead title="内容安全" />
      <Card title="各机构的心理危机预警" size="small" extra="超过时限没处理的算超时，需要提醒学校">
        <Table
          size="small"
          rowKey="tenant_id"
          loading={alerts.isLoading}
          dataSource={alerts.data}
          pagination={false}
          locale={{ emptyText: "还没有危机预警" }}
          columns={[
            { title: "机构", dataIndex: "tenant_name" },
            {
              title: "待处理",
              dataIndex: "open",
              align: "right",
              render: (n, r) => (
                <Space size={4}>
                  {n}
                  {r.overdue > 0 && <Tag color="red">{r.overdue} 条超时</Tag>}
                </Space>
              ),
            },
            { title: "已处理", dataIndex: "handled", align: "right" },
            { title: "其中高风险", dataIndex: "high", align: "right" },
          ]}
        />
      </Card>

      <Card title="被拦下的消息和危机信号" size="small">
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
            placeholder="全部类别"
            style={{ width: 140 }}
            value={category}
            onChange={(v) => {
              setCategory(v);
              setPage(1);
            }}
            options={Object.entries(CATEGORY).map(([value, c]) => ({ value, label: c.label }))}
          />
          <Checkbox
            checked={crisisOnly}
            onChange={(e) => {
              setCrisisOnly(e.target.checked);
              setPage(1);
            }}
          >
            只看危机信号
          </Checkbox>
        </Space>
        <Table
          size="small"
          rowKey="id"
          loading={logs.isLoading}
          dataSource={logs.data?.items}
          scroll={{ x: 820 }}
          pagination={{
            current: page,
            pageSize,
            total: logs.data?.total ?? 0,
            onChange: setPage,
            showTotal: (n) => `共 ${n} 条`,
          }}
          columns={[
            { title: "时间", dataIndex: "created_at", width: 120, render: (t) => dayjs(t).format("MM-DD HH:mm") },
            { title: "机构", dataIndex: "tenant_name", width: 140 },
            {
              title: "类别",
              dataIndex: "category",
              width: 100,
              render: (c) => <Tag color={CATEGORY[c]?.color}>{CATEGORY[c]?.label ?? c}</Tag>,
            },
            { title: "危机信号", dataIndex: "crisis", width: 110, render: crisisTag },
            {
              title: "学生说的话",
              dataIndex: "excerpt",
              render: (t: string, r) => (
                <Space orientation="vertical" size={0}>
                  <Typography.Paragraph ellipsis={{ rows: 2, expandable: true }} style={{ marginBottom: 0 }}>
                    {t}
                  </Typography.Paragraph>
                  {r.reason && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      判断依据：{r.reason}
                    </Typography.Text>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
