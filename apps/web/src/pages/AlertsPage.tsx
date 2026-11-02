import { CheckOutlined, MessageOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Drawer, Empty, Form, Input, Modal, Segmented, Space, Spin, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";
import { PageHead } from "@/components/PageHead";

type AlertOut = Schemas["AlertOut"];

function Conversation({ alert, onClose }: { alert: AlertOut | null; onClose: () => void }) {
  const msgs = useQuery({
    queryKey: ["alerts", alert?.id, "messages"],
    enabled: Boolean(alert),
    queryFn: async () => unwrap(await api.GET("/api/alerts/{alert_id}/messages", { params: { path: { alert_id: alert!.id } } })),
  });
  return (
    <Drawer title={alert ? `${alert.student_name} 的问一问记录` : ""} open={Boolean(alert)} onClose={onClose} size="large">
      <Typography.Paragraph type="secondary">只用于了解情况、关心学生，请注意保护学生隐私。</Typography.Paragraph>
      <Spin spinning={msgs.isLoading}>
        {msgs.data?.map((m) => (
          <div key={m.id} className={m.role === "user" ? "bubble bubble-user" : "bubble bubble-ai"}>
            {m.flag === "crisis" && m.role === "assistant" && <Tag color="red">危机回复</Tag>}
            {m.role === "assistant" ? <MarkdownView text={m.content} /> : <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {dayjs(m.created_at).format("MM-DD HH:mm")}
            </Typography.Text>
          </div>
        ))}
      </Spin>
    </Drawer>
  );
}

/** 心理预警：老师看自己班学生的，机构管理员看全部。必须确认处理并填写记录。 */
export function AlertsPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [status, setStatus] = useState<string>("open");
  const [viewing, setViewing] = useState<AlertOut | null>(null);
  const [handling, setHandling] = useState<AlertOut | null>(null);
  const [form] = Form.useForm<{ note: string }>();
  const alerts = useQuery({
    queryKey: ["alerts", status],
    queryFn: async () => unwrap(await api.GET("/api/alerts", { params: { query: { status: status === "all" ? undefined : status } } })),
    refetchInterval: 60_000,
  });
  const handle = useMutation({
    mutationFn: async (note: string) =>
      unwrap(await api.POST("/api/alerts/{alert_id}/handle", { params: { path: { alert_id: handling!.id } }, body: { note } })),
    onSuccess: () => {
      message.success("已记录处理情况");
      setHandling(null);
      form.resetFields();
      qc.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (e) => message.error(e.message),
  });
  const overdue = (alerts.data ?? []).filter((a) => a.overdue).length;

  return (
    <>
      <PageHead title="心理预警" />
      <Alert
        type="info"
        showIcon
        title="学生在问一问里流露出自伤、轻生、被欺负等信号时，系统会给学生显示求助电话，并在这里生成预警。"
        description="请尽快和学生本人、家长沟通，必要时联系学校心理老师；处理后填写记录。超过 2 小时没处理的会标为超时。"
        style={{ marginBottom: 16 }}
      />
      <Space style={{ marginBottom: 16 }} wrap>
        <Segmented
          value={status}
          onChange={(v) => setStatus(String(v))}
          options={[
            { value: "open", label: "待处理" },
            { value: "handled", label: "已处理" },
            { value: "all", label: "全部" },
          ]}
        />
        {overdue > 0 && <Tag color="red">{overdue} 条已超时</Tag>}
      </Space>
      <Table
        rowKey="id"
        loading={alerts.isLoading}
        dataSource={alerts.data}
        scroll={{ x: 820 }}
        locale={{ emptyText: <Empty description={status === "open" ? "没有待处理的预警" : "没有记录"} /> }}
        columns={[
          {
            title: "学生",
            width: 150,
            render: (_, a) => (
              <>
                <Typography.Text strong>{a.student_name}</Typography.Text>
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {a.class_names.join("、")}
                  </Typography.Text>
                </div>
              </>
            ),
          },
          {
            title: "等级",
            dataIndex: "level",
            width: 100,
            render: (level: string, a) => (
              <Space orientation="vertical" size={2}>
                <Tag color={level === "high" ? "red" : "orange"}>{level === "high" ? "高风险" : "需要关注"}</Tag>
                {a.overdue && <Tag color="red">超时</Tag>}
              </Space>
            ),
          },
          {
            title: "学生原话",
            dataIndex: "excerpt",
            render: (t: string) => <Typography.Paragraph ellipsis={{ rows: 2, expandable: true, symbol: "展开" }} style={{ margin: 0 }}>{t}</Typography.Paragraph>,
          },
          { title: "时间", dataIndex: "created_at", width: 120, render: (t: string) => dayjs(t).format("MM-DD HH:mm") },
          {
            title: "处理",
            width: 220,
            render: (_, a) => (
              <Space orientation="vertical" size={4}>
                <Space size={0}>
                  <Button type="link" size="small" icon={<MessageOutlined />} onClick={() => setViewing(a)}>
                    看对话
                  </Button>
                  {a.status === "open" && (
                    <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => setHandling(a)}>
                      填写处理记录
                    </Button>
                  )}
                </Space>
                {a.status === "handled" && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {a.handled_by_name} {a.handled_at && dayjs(a.handled_at).format("MM-DD HH:mm")}：{a.note}
                  </Typography.Text>
                )}
              </Space>
            ),
          },
        ]}
      />
      <Conversation alert={viewing} onClose={() => setViewing(null)} />
      <Modal
        title={handling ? `处理 ${handling.student_name} 的预警` : ""}
        open={Boolean(handling)}
        onCancel={() => setHandling(null)}
        onOk={() => form.submit()}
        okButtonProps={{ loading: handle.isPending }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(v) => handle.mutate(v.note)}>
          <Form.Item name="note" label="处理记录" rules={[{ required: true, min: 2, message: "请填写处理情况" }]}>
            <Input.TextArea rows={4} maxLength={2000} placeholder="例如：已当面和学生谈话，联系了家长，转介学校心理老师，下周复查" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
