import { CheckOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App, AutoComplete, Button, Card, Col, Empty, Form, Input, InputNumber, Progress, Row, Select, Space, Spin, Steps, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, unwrap } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { LibraryField } from "./docGenerate";
import { GRADES, SUBJECTS, TEXTBOOKS } from "./lessonPlanOptions";
import { ReferenceField } from "./LessonPlanNewPage";
import { DIFFICULTIES, QTYPES, QuestionEditModal, QuestionItem, useInvalidateQuestions, type QuestionGenIn, type QuestionOut } from "./questionUi";

const DEFAULTS: Partial<QuestionGenIn> = {
  subject: "数学",
  grade: "七年级上册",
  textbook: "人教版",
  qtype: "单选题",
  difficulty: "中等",
  count: 5,
  use_library: true,
  resource_ids: [],
};

function BatchPanel({ batchId }: { batchId: string }) {
  const { message } = App.useApp();
  const invalidate = useInvalidateQuestions();
  const [editing, setEditing] = useState<Partial<QuestionOut> | null>(null);
  const batch = useQuery({
    queryKey: ["teacher", "question-batch", batchId],
    queryFn: async () =>
      unwrap(await api.GET("/api/teacher/question-batches/{batch_id}", { params: { path: { batch_id: batchId } } })),
    refetchInterval: (q) => {
      const b = q.state.data;
      const busy = !b || b.status === "generating" || b.status === "checking" || b.questions.some((x) => x.status === "checking");
      return busy ? 2000 : false;
    },
  });
  const checked = (batch.data?.questions ?? []).filter((q) => q.status === "checked");
  const approveChecked = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/teacher/questions/bulk-review", { body: { ids: checked.map((q) => q.id), approve: true } })),
    onSuccess: (r) => {
      message.success(`${r.count} 道题已入库`);
      invalidate();
    },
    onError: (e) => message.error(e.message),
  });

  const b = batch.data;
  if (!b) return <Spin style={{ display: "block", margin: "64px auto" }} />;
  const step = b.status === "generating" ? 0 : b.status === "checking" ? 1 : 2;
  const pending = b.questions.filter((q) => ["checked", "disputed", "unchecked"].includes(q.status)).length;

  return (
    <>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Steps
          size="small"
          current={step}
          status={b.status === "failed" ? "error" : undefined}
          items={[
            { title: "出题", content: "AI 按要求出题" },
            { title: "校验", content: "推理模型独立解题、核对答案" },
            { title: "审核", content: "你确认后入库" },
          ]}
        />
        {(b.status === "generating" || b.status === "checking") && (
          <Progress percent={b.progress} status="active" style={{ marginTop: 12, marginBottom: 0 }} />
        )}
        {b.status === "generating" && (
          <Typography.Paragraph type="secondary" style={{ margin: "8px 0 0" }}>
            AI 正在出题，大约需要半分钟到一分钟；离开页面不影响，之后可以在「题库 → 待审核」里看到。
          </Typography.Paragraph>
        )}
        {b.status === "failed" && <Alert type="error" showIcon title={b.error} style={{ marginTop: 12 }} />}
        {b.warnings.length > 0 && <Alert type="warning" showIcon title={b.warnings.join("；")} style={{ marginTop: 12 }} />}
        {b.sources.length > 0 && (
          <Typography.Paragraph type="secondary" style={{ margin: "8px 0 0" }}>
            参考了资料库：{[...new Set(b.sources.map((s) => String(s.label)))].join("、")}
          </Typography.Paragraph>
        )}
      </Card>
      {b.status === "done" && (
        <Space wrap style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<CheckOutlined />} disabled={!checked.length} loading={approveChecked.isPending} onClick={() => approveChecked.mutate()}>
            校验一致的 {checked.length} 道全部入库
          </Button>
          <Typography.Text type="secondary">
            {pending ? `还有 ${pending} 道待审核，有分歧的请重点看。` : "这批题都审核完了。"}
            <Link to="/teacher/questions">去题库</Link>
          </Typography.Text>
        </Space>
      )}
      {b.questions.map((q, i) => (
        <div key={q.id} style={{ marginBottom: 12 }}>
          <QuestionItem q={q} index={i} onEdit={setEditing} />
        </div>
      ))}
      <QuestionEditModal question={editing} onClose={() => setEditing(null)} />
    </>
  );
}

export function QuestionGenPage() {
  const { message } = App.useApp();
  const [params, setParams] = useSearchParams();
  const batchId = params.get("batch");
  const [form] = Form.useForm<QuestionGenIn>();
  const subject = Form.useWatch("subject", form);
  const useLibrary = Form.useWatch("use_library", form);

  // 打开以前的出题记录：回填当时的参数，方便“再出一批”
  const previous = useQuery({
    queryKey: ["teacher", "question-batch", batchId],
    enabled: Boolean(batchId),
    queryFn: async () => unwrap(await api.GET("/api/teacher/question-batches/{batch_id}", { params: { path: { batch_id: batchId! } } })),
  });
  const [filled, setFilled] = useState(false);
  useEffect(() => {
    if (!filled && previous.data?.params) {
      form.setFieldsValue(previous.data.params);
      setFilled(true);
    }
  }, [previous.data, filled, form]);

  const generate = useMutation({
    mutationFn: async (body: QuestionGenIn) => unwrap(await api.POST("/api/teacher/questions/generate", { body })),
    onSuccess: (b) => {
      setFilled(true);
      setParams({ batch: b.id });
    },
    onError: (e) => message.error(e.message),
  });

  return (
    <>
      <PageHead title="AI 出题" />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card>
            <Form form={form} layout="vertical" initialValues={DEFAULTS} onFinish={(v) => generate.mutate(v)}>
              <Row gutter={12}>
                <Col span={10}>
                  <Form.Item name="subject" label="学科" rules={[{ required: true }]}>
                    <Select options={SUBJECTS.map((s) => ({ value: s, label: s }))} />
                  </Form.Item>
                </Col>
                <Col span={14}>
                  <Form.Item name="grade" label="年级" rules={[{ required: true }]}>
                    <Select options={GRADES.map((g) => ({ value: g, label: g }))} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="topic" label="知识点" rules={[{ required: true, whitespace: true, message: "请填写知识点" }]}>
                <Input maxLength={200} placeholder="例如：有理数的加法法则、一般现在时的第三人称单数" />
              </Form.Item>
              <Row gutter={12}>
                <Col span={9}>
                  <Form.Item name="qtype" label="题型">
                    <Select options={QTYPES.map((t) => ({ value: t, label: t }))} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="difficulty" label="难度">
                    <Select options={DIFFICULTIES.map((d) => ({ value: d, label: d }))} />
                  </Form.Item>
                </Col>
                <Col span={7}>
                  <Form.Item name="count" label="道数">
                    <InputNumber min={1} max={10} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="textbook" label="教材版本" rules={[{ required: true, whitespace: true }]}>
                <AutoComplete options={TEXTBOOKS.map((t) => ({ value: t }))} maxLength={30} />
              </Form.Item>
              <Form.Item name="requirements" label="补充要求（选填）">
                <Input.TextArea rows={2} maxLength={1000} showCount placeholder="例如：结合生活情境；重点考符号法则的易错点" />
              </Form.Item>
              <LibraryField subject={subject} enabled={useLibrary !== false} hint="按知识点检索资料，作为命题依据" />
              <ReferenceField label="粘贴参考题（选填）" extra="粘贴几道例题或真题，AI 会参照风格和难度出新题，不会照抄" />
              <Button type="primary" htmlType="submit" block size="large" icon={<ThunderboltOutlined />} loading={generate.isPending}>
                {batchId ? "再出一批" : "开始出题"}
              </Button>
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          {batchId ? (
            <BatchPanel key={batchId} batchId={batchId} />
          ) : (
            <Card>
              <Empty
                style={{ padding: "48px 0" }}
                description={
                  <>
                    填好左边的信息，点击“开始出题”。
                    <br />
                    出完题会自动用推理模型独立解一遍、核对答案，你审核后才进题库。
                  </>
                }
              />
            </Card>
          )}
        </Col>
      </Row>
    </>
  );
}
