import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Descriptions, Space, Table, Typography } from "antd";
import { api, unwrap } from "@/api/client";
import { SKILL_LABEL, yuan } from "@/components/labels";
import { PageHead } from "@/components/PageHead";
import { expiryTag, QuotaMeter, quotaLevel } from "@/components/QuotaMeter";

export function OverviewPage() {
  const overview = useQuery({ queryKey: ["org", "overview"], queryFn: async () => unwrap(await api.GET("/api/org/overview")) });
  const o = overview.data;
  const spend = Number(o?.ai_spend_yuan ?? 0);
  const budget = o?.ai_budget_yuan == null ? null : Number(o.ai_budget_yuan);
  const aiLevel = quotaLevel(spend, budget);

  return (
    <Space orientation="vertical" size="large" style={{ width: "100%" }}>
      <PageHead title="机构概况" />
      {aiLevel && aiLevel.ratio >= 1 && (
        <Alert
          type="error"
          showIcon
          title="本月的 AI 额度已经用完"
          description="老师生成教案、出题，学生问一问、AI 批改都暂停了，下个月 1 日恢复。需要增加额度请联系平台。"
        />
      )}
      <Card size="small" loading={overview.isLoading}>
        <Descriptions
          column={{ xs: 1, sm: 2, md: 3 }}
          items={[
            { label: "机构", children: o?.name },
            { label: "学生登录用的机构代码", children: <Typography.Text code>{o?.code}</Typography.Text> },
            { label: "套餐", children: o?.plan_name ?? "—" },
            { label: "服务到期", children: expiryTag(o?.expires_at) },
          ]}
        />
      </Card>
      <div className="kpi-row">
        <Card size="small" loading={overview.isLoading}>
          <QuotaMeter label="学生账号" used={o?.students.used ?? 0} quota={o?.students.quota} />
        </Card>
        <Card size="small" loading={overview.isLoading}>
          <QuotaMeter label="老师账号（含管理员）" used={o?.teachers.used ?? 0} quota={o?.teachers.quota} />
        </Card>
        <Card size="small" loading={overview.isLoading}>
          <QuotaMeter label="本月 AI 费用" used={spend} quota={budget} format={yuan} />
        </Card>
      </div>
      <Typography.Text type="secondary">
        名额只算启用中的账号：毕业、离职的在“学生”“老师”里停用后就不占名额。AI 费用按自然月统计，每月 1 日重新计算。
      </Typography.Text>
      <Card title="本月 AI 用在了哪里" size="small">
        <Table
          size="small"
          rowKey="skill"
          loading={overview.isLoading}
          dataSource={o?.ai_by_skill}
          pagination={false}
          locale={{ emptyText: "本月还没有使用 AI" }}
          columns={[
            { title: "功能", dataIndex: "skill", render: (s) => SKILL_LABEL[s] ?? s },
            { title: "次数", dataIndex: "calls", align: "right" },
            { title: "费用", dataIndex: "cost_yuan", align: "right", render: yuan },
          ]}
        />
      </Card>
    </Space>
  );
}
