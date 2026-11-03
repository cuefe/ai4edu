import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, Select, Space, Table, Tag, Typography } from "antd";
import { api, unwrap } from "@/api/client";
import { SKILL_LABEL } from "@/components/labels";
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
  const status = useQuery({ queryKey: ["ops", "ai", "status"], queryFn: async () => unwrap(await api.GET("/api/ops/ai/status")) });
  const test = useMutation({
    mutationFn: async (v: { skill: string; prompt: string }) => unwrap(await api.POST("/api/ops/ai/test", { body: v })),
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
      <Card title="功能与模型路由" size="small" extra="价格和路由在 server/app/ai/gateway/models.yaml 里改">
        <Table
          size="small"
          rowKey="skill"
          loading={status.isLoading}
          dataSource={status.data}
          pagination={false}
          scroll={{ x: 520 }}
          columns={[
            {
              title: "功能",
              dataIndex: "skill",
              render: (s) => (
                <Space size={4}>
                  {SKILL_LABEL[s] ?? s}
                  <Typography.Text type="secondary" code>
                    {s}
                  </Typography.Text>
                </Space>
              ),
            },
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
          <Form.Item name="skill" label="功能">
            <Select
              style={{ maxWidth: 240 }}
              options={(status.data ?? []).map((s) => ({ value: s.skill, label: SKILL_LABEL[s.skill] ?? s.skill }))}
            />
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
    </Space>
  );
}
