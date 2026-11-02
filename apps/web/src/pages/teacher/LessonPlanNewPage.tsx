import { ThunderboltOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, App, AutoComplete, Button, Card, Col, Collapse, Empty, Form, Input, InputNumber, Row, Select, Spin, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, unwrap } from "@/api/client";
import { postSSE } from "@/api/sse";
import { MarkdownView } from "@/components/MarkdownView";
import { PageHead } from "@/components/PageHead";
import { GRADES, LESSON_TYPES, SUBJECTS, TEXTBOOKS, type LessonPlanIn } from "./lessonPlanOptions";

const DEFAULTS: Partial<LessonPlanIn> = { subject: "数学", grade: "七年级上册", textbook: "人教版", lesson_type: "新授课", duration: 45 };

type Phase = "idle" | "streaming" | "error";

export function LessonPlanNewPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [params] = useSearchParams();
  const fromId = params.get("from");
  const [form] = Form.useForm<LessonPlanIn>();
  const [phase, setPhase] = useState<Phase>("idle");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const previewRef = useRef<HTMLDivElement>(null);

  // "重新生成"：用原教案的参数填表
  const source = useQuery({
    queryKey: ["teacher", "document", fromId],
    enabled: Boolean(fromId),
    queryFn: async () => unwrap(await api.GET("/api/teacher/documents/{doc_id}", { params: { path: { doc_id: fromId! } } })),
  });
  useEffect(() => {
    if (source.data?.params) form.setFieldsValue(source.data.params);
  }, [source.data, form]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // 内容在底部附近时跟着滚动；老师往上翻看时不打扰
  useEffect(() => {
    const el = previewRef.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 120) el.scrollTop = el.scrollHeight;
  }, [text]);

  async function generate(values: LessonPlanIn) {
    const abort = new AbortController();
    abortRef.current = abort;
    setPhase("streaming");
    setText("");
    setError("");
    // 攒一小段再刷新，避免每个字都重新渲染整篇 Markdown
    let buffer = "";
    let timer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      const chunk = buffer;
      buffer = "";
      timer = null;
      setText((t) => t + chunk);
    };
    try {
      await postSSE(
        "/api/teacher/lesson-plans/generate",
        values,
        (event, data) => {
          const d = data as { id?: string; text?: string; message?: string };
          if (event === "delta" && d.text) {
            buffer += d.text;
            timer ??= setTimeout(flush, 100);
          } else if (event === "done") {
            message.success("教案生成好了，可以直接修改");
            navigate(`/teacher/lesson-plans/${d.id}`, { replace: true });
          } else if (event === "error") {
            throw new Error(d.message);
          }
        },
        abort.signal,
      );
    } catch (e) {
      if (abort.signal.aborted) return;
      setPhase("error");
      setError(e instanceof Error ? e.message : "生成失败，请稍后重试");
    } finally {
      if (timer) clearTimeout(timer);
      flush();
    }
  }

  const streaming = phase === "streaming";

  return (
    <>
      <PageHead title={fromId ? "重新生成教案" : "AI 生成教案"} />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card>
            <Spin spinning={source.isLoading}>
              <Form form={form} layout="vertical" initialValues={DEFAULTS} onFinish={generate} disabled={streaming}>
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
                <Form.Item name="topic" label="课题" rules={[{ required: true, whitespace: true, message: "请填写课题" }]}>
                  <Input maxLength={100} placeholder="例如：1.2.1 有理数的概念、Unit 3 Section A" />
                </Form.Item>
                <Row gutter={12}>
                  <Col span={10}>
                    <Form.Item name="lesson_type" label="课型">
                      <Select options={LESSON_TYPES.map((t) => ({ value: t, label: t }))} />
                    </Form.Item>
                  </Col>
                  <Col span={14}>
                    <Form.Item name="textbook" label="教材版本" rules={[{ required: true, whitespace: true }]}>
                      <AutoComplete options={TEXTBOOKS.map((t) => ({ value: t }))} maxLength={30} />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item name="duration" label="课时长度">
                  <InputNumber min={30} max={90} suffix="分钟" style={{ width: 140 }} />
                </Form.Item>
                <Form.Item name="requirements" label="补充要求（选填）">
                  <Input.TextArea
                    rows={3}
                    maxLength={1000}
                    showCount
                    placeholder="例如：学生基础较弱，多安排小组合作；重点讲数轴上的表示"
                  />
                </Form.Item>
                <Collapse
                  ghost
                  size="small"
                  style={{ marginBottom: 16, marginInline: -16 }}
                  items={[
                    {
                      key: "ref",
                      label: "参考资料（选填）",
                      forceRender: true,
                      children: (
                        <Form.Item
                          name="reference"
                          extra="粘贴教材原文、已有教案或教参片段，AI 会以它为准，减少编造"
                          style={{ marginBottom: 0 }}
                        >
                          <Input.TextArea rows={6} maxLength={8000} showCount />
                        </Form.Item>
                      ),
                    },
                  ]}
                />
                <Button type="primary" htmlType="submit" block size="large" icon={<ThunderboltOutlined />} loading={streaming}>
                  {streaming ? "正在生成…" : "生成教案"}
                </Button>
              </Form>
            </Spin>
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <Card
            title="预览"
            extra={streaming && <Typography.Text type="secondary">大约需要 1～2 分钟，离开页面不影响生成</Typography.Text>}
            styles={{ body: { padding: 0 } }}
          >
            {phase === "error" && (
              <Alert
                type="error"
                showIcon
                title={error}
                description="可以稍后重试；如果已经生成了一部分，能在教案列表里看到。"
                style={{ margin: 16 }}
              />
            )}
            <div ref={previewRef} className="doc-preview">
              {text ? (
                <MarkdownView text={text} />
              ) : (
                <Empty
                  style={{ padding: "64px 0" }}
                  description={streaming ? "AI 正在构思…" : "填好左边的信息，点击“生成教案”"}
                  image={streaming ? <Spin size="large" /> : Empty.PRESENTED_IMAGE_SIMPLE}
                />
              )}
            </div>
          </Card>
        </Col>
      </Row>
    </>
  );
}
