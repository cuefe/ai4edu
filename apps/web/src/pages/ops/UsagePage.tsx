import { useQuery } from "@tanstack/react-query";
import { Card, Segmented, Space, Statistic, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { SKILL_LABEL, yuan } from "@/components/labels";
import { PageHead } from "@/components/PageHead";

const tokens = (n: number) => (n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : String(n));

export function UsagePage() {
  const [days, setDays] = useState(30);
  const summary = useQuery({
    queryKey: ["ops", "usage", "summary", days],
    queryFn: async () => unwrap(await api.GET("/api/ops/usage/summary", { params: { query: { days } } })),
  });
  const detail = useQuery({
    queryKey: ["ops", "ai", "usage", days],
    queryFn: async () => unwrap(await api.GET("/api/ops/ai/usage", { params: { query: { days } } })),
  });
  const total = summary.data?.total;
  const failRate = total && total.calls ? (total.failures / total.calls) * 100 : 0;

  return (
    <Space orientation="vertical" size="large" style={{ width: "100%" }}>
      <PageHead
        title="AI 用量"
        extra={
          <Segmented
            value={days}
            onChange={(v) => setDays(v as number)}
            options={[
              { label: "近 7 天", value: 7 },
              { label: "近 30 天", value: 30 },
              { label: "近 90 天", value: 90 },
            ]}
          />
        }
      />
      <div className="kpi-row">
        <Card size="small">
          <Statistic title="调用次数" value={total?.calls ?? 0} loading={summary.isLoading} />
        </Card>
        <Card size="small">
          <Statistic title="费用（按官网原价估算）" value={yuan(total?.cost_yuan)} loading={summary.isLoading} />
        </Card>
        <Card size="small">
          <Statistic
            title="失败率"
            value={failRate.toFixed(1)}
            suffix="%"
            loading={summary.isLoading}
          />
          {total && total.failures > 0 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {total.failures} 次失败（失败后会换备用模型重试）
            </Typography.Text>
          )}
        </Card>
        <Card size="small">
          <Statistic
            title="输入 / 输出 token"
            value={`${tokens(total?.prompt_tokens ?? 0)} / ${tokens(total?.completion_tokens ?? 0)}`}
            loading={summary.isLoading}
          />
        </Card>
      </div>

      <Card title="按机构" size="small">
        <Table
          size="small"
          rowKey={(r) => r.tenant_id ?? "platform"}
          loading={summary.isLoading}
          dataSource={summary.data?.by_tenant}
          pagination={false}
          scroll={{ x: 560 }}
          columns={[
            { title: "机构", dataIndex: "tenant_name", render: (n) => n ?? "平台（运营后台测试）" },
            { title: "调用", dataIndex: "calls", align: "right" },
            { title: "失败", dataIndex: "failures", align: "right", render: (n) => (n ? <Tag color="red">{n}</Tag> : 0) },
            { title: "费用", dataIndex: "cost_yuan", align: "right", render: yuan },
          ]}
        />
      </Card>

      <Card title="按天" size="small">
        <Table
          size="small"
          rowKey="day"
          loading={summary.isLoading}
          dataSource={[...(summary.data?.daily ?? [])].reverse()}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          columns={[
            { title: "日期", dataIndex: "day", render: (d) => dayjs(d).format("MM-DD ddd") },
            { title: "调用", dataIndex: "calls", align: "right" },
            { title: "费用", dataIndex: "cost_yuan", align: "right", render: yuan },
          ]}
        />
      </Card>

      <Card title="明细（按机构、功能、模型）" size="small">
        <Table
          size="small"
          rowKey={(r) => `${r.tenant_id}-${r.skill}-${r.provider}-${r.model}`}
          loading={detail.isLoading}
          dataSource={detail.data}
          scroll={{ x: 820 }}
          columns={[
            { title: "机构", dataIndex: "tenant_name", render: (n) => n ?? "平台" },
            { title: "功能", dataIndex: "skill", render: (s) => SKILL_LABEL[s] ?? s },
            { title: "模型", render: (_, r) => `${r.provider} / ${r.model}` },
            { title: "调用", dataIndex: "calls", align: "right" },
            { title: "失败", dataIndex: "failures", align: "right", render: (n) => (n ? <Tag color="red">{n}</Tag> : 0) },
            { title: "输入 token", dataIndex: "prompt_tokens", align: "right" },
            { title: "输出 token", dataIndex: "completion_tokens", align: "right" },
            {
              title: "费用",
              dataIndex: "cost_yuan",
              align: "right",
              render: (c) => (c == null ? <Typography.Text type="secondary">未配置价格</Typography.Text> : yuan(c)),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
