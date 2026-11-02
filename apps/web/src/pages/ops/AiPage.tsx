import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, Segmented, Select, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { PageHead } from "@/components/PageHead";

const TIER_LABEL: Record<string, string> = {
  flagship: "旗舰",
  standard: "中档",
  reasoning: "推理",
  vision: "多模态",
  fast: "低延迟",
};

export function AiPage() {
  const { message } = App.useApp();
  const [days, setDays] = useState(7);
  const status = useQuery({ queryKey: ["ops", "ai", "status"], queryFn: async () => unwrap(await api.GET("/api/ops/ai/status")) });
  const usage = useQuery({
    queryKey: ["ops", "ai", "usage", days],
    queryFn: async () => unwrap(await api.GET("/api/ops/ai/usage", { params: { query: { days } } })),
  });
  const test = useMutation({
    mutationFn: async (v: { skill: string; prompt: string }) => unwrap(await api.POST("/api/ops/ai/test", { body: v })),
    onSuccess: () => usage.refetch(),
    onError: (e) => message.error(e.message),
  });

  const onlyMock = status.data?.every((s) => s.candidates.every((c) => c.provider === "mock"));

  return (
    <Space orientation="vertical" size="large" style={{ width: "100%" }}>
      <PageHead title="AI 模型" />
      {onlyMock && (
        <Alert
          type="warning"
          showIcon
          title="还没有配置任何大模型 API Key，当前使用 mock 模型（只回显输入）"
          description="在 server/.env 里填写 DEEPSEEK_API_KEY 和 DASHSCOPE_API_KEY 后重启后端。"
        />
      )}
      <Card title="技能与模型路由" size="small">
        <Table
          size="small"
          rowKey="skill"
          loading={status.isLoading}
          dataSource={status.data}
          pagination={false}
          scroll={{ x: 520 }}
          columns={[
            { title: "技能", dataIndex: "skill", render: (s) => <Typography.Text code>{s}</Typography.Text> },
            { title: "档位", dataIndex: "tier", render: (t) => TIER_LABEL[t] ?? t },
            {
              title: "可用模型（按优先级）",
              render: (_, s) =>
                s.candidates.length ? (
                  s.candidates.map((c, i) => (
                    <Tag key={`${c.provider}-${c.model}`} color={i === 0 ? "blue" : undefined}>
                      {c.provider} / {c.model}
                    </Tag>
                  ))
                ) : (
                  <Tag color="red">无可用模型</Tag>
                ),
            },
          ]}
        />
      </Card>
      <Card title="调用测试" size="small">
        <Form layout="vertical" initialValues={{ skill: "ping", prompt: "用一句话介绍勾股定理" }} onFinish={(v) => test.mutate(v)}>
          <Form.Item name="skill" label="技能">
            <Select style={{ maxWidth: 240 }} options={(status.data ?? []).map((s) => ({ value: s.skill, label: s.skill }))} />
          </Form.Item>
          <Form.Item name="prompt" label="输入" rules={[{ required: true }]}>
            <Input.TextArea rows={3} maxLength={2000} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={test.isPending}>
            发送
          </Button>
        </Form>
        {test.data && (
          <Alert
            style={{ marginTop: 16 }}
            type="success"
            title={`${test.data.provider} / ${test.data.model} · ${test.data.latency_ms} ms · 输入 ${test.data.prompt_tokens} / 输出 ${test.data.completion_tokens} token`}
            description={<Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{test.data.text}</Typography.Paragraph>}
          />
        )}
      </Card>
      <Card
        title="用量"
        size="small"
        extra={
          <Segmented
            value={days}
            onChange={(v) => setDays(v as number)}
            options={[
              { label: "7 天", value: 7 },
              { label: "30 天", value: 30 },
            ]}
          />
        }
      >
        <Table
          size="small"
          rowKey={(r) => `${r.tenant_id}-${r.skill}-${r.provider}-${r.model}`}
          loading={usage.isLoading}
          dataSource={usage.data}
          scroll={{ x: 720 }}
          columns={[
            { title: "机构", dataIndex: "tenant_name", render: (n) => n ?? "平台" },
            { title: "技能", dataIndex: "skill" },
            { title: "模型", render: (_, r) => `${r.provider} / ${r.model}` },
            { title: "调用", dataIndex: "calls" },
            { title: "失败", dataIndex: "failures", render: (n) => (n ? <Tag color="red">{n}</Tag> : 0) },
            { title: "输入 token", dataIndex: "prompt_tokens" },
            { title: "输出 token", dataIndex: "completion_tokens" },
            { title: "费用（元）", dataIndex: "cost_yuan", render: (c) => (c == null ? "未配置价格" : Number(c).toFixed(4)) },
          ]}
        />
      </Card>
    </Space>
  );
}
