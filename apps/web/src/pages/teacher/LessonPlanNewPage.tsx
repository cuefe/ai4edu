import { ThunderboltOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { AutoComplete, Button, Card, Col, Collapse, Form, Input, InputNumber, Row, Select, Spin } from "antd";
import { useEffect } from "react";
import { useSearchParams } from "react-router";
import { api, unwrap } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { LibraryField, PreviewCard, useDocStream } from "./docGenerate";
import { GRADES, LESSON_TYPES, SUBJECTS, TEXTBOOKS, type LessonPlanIn } from "./lessonPlanOptions";

const DEFAULTS: Partial<LessonPlanIn> = {
  subject: "数学",
  grade: "七年级上册",
  textbook: "人教版",
  lesson_type: "新授课",
  duration: 45,
  use_library: true,
  resource_ids: [],
};

export function LessonPlanNewPage() {
  const [params] = useSearchParams();
  const fromId = params.get("from");
  const [form] = Form.useForm<LessonPlanIn>();
  const subject = Form.useWatch("subject", form);
  const useLibrary = Form.useWatch("use_library", form);
  const stream = useDocStream("lesson_plan");

  // "重新生成"：用原教案的参数填表
  const source = useQuery({
    queryKey: ["teacher", "document", fromId],
    enabled: Boolean(fromId),
    queryFn: async () => unwrap(await api.GET("/api/teacher/documents/{doc_id}", { params: { path: { doc_id: fromId! } } })),
  });
  useEffect(() => {
    if (source.data?.params) form.setFieldsValue(source.data.params as LessonPlanIn);
  }, [source.data, form]);

  return (
    <>
      <PageHead title={fromId ? "重新生成教案" : "AI 生成教案"} />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card>
            <Spin spinning={source.isLoading}>
              <Form form={form} layout="vertical" initialValues={DEFAULTS} onFinish={stream.generate} disabled={stream.streaming}>
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
                <LibraryField subject={subject} enabled={useLibrary !== false} hint="按课题检索相关内容，教案里标注出处" />
                <ReferenceField extra="粘贴教材原文、已有教案或教参片段，AI 会以它为准，减少编造" />
                <Button type="primary" htmlType="submit" block size="large" icon={<ThunderboltOutlined />} loading={stream.streaming}>
                  {stream.streaming ? "正在生成…" : "生成教案"}
                </Button>
              </Form>
            </Spin>
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <PreviewCard stream={stream} idleHint="填好左边的信息，点击“生成教案”" />
        </Col>
      </Row>
    </>
  );
}

/** 折叠起来的“粘贴参考资料”，教案、讲义、出题共用。 */
export function ReferenceField({ extra, label = "粘贴参考资料（选填）" }: { extra: string; label?: string }) {
  return (
    <Collapse
      ghost
      size="small"
      style={{ marginBottom: 16, marginInline: -16 }}
      items={[
        {
          key: "ref",
          label,
          forceRender: true,
          children: (
            <Form.Item name="reference" extra={extra} style={{ marginBottom: 0 }}>
              <Input.TextArea rows={6} maxLength={8000} showCount />
            </Form.Item>
          ),
        },
      ]}
    />
  );
}
