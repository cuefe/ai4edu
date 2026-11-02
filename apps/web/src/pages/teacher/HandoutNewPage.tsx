import { ThunderboltOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { AutoComplete, Button, Card, Col, Form, Input, Radio, Row, Select, Spin } from "antd";
import { useEffect } from "react";
import { useSearchParams } from "react-router";
import { api, unwrap } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { LibraryField, PreviewCard, useDocStream } from "./docGenerate";
import { GRADES, HANDOUT_KINDS, SUBJECTS, TEXTBOOKS, type HandoutIn } from "./lessonPlanOptions";
import { ReferenceField } from "./LessonPlanNewPage";

const DEFAULTS: Partial<HandoutIn> = {
  subject: "数学",
  grade: "七年级上册",
  textbook: "人教版",
  kind: "课堂讲义",
  use_library: true,
  resource_ids: [],
};

const KIND_HINT: Record<string, string> = {
  课堂讲义: "学习目标、知识梳理（标出考点）、典型例题、易错提醒、课堂练习和答案",
  复习讲义: "知识框架、按考点梳理并配例题、易错提醒、巩固练习和答案",
};

export function HandoutNewPage() {
  const [params] = useSearchParams();
  const fromId = params.get("from");
  const [form] = Form.useForm<HandoutIn>();
  const subject = Form.useWatch("subject", form);
  const kind = Form.useWatch("kind", form);
  const useLibrary = Form.useWatch("use_library", form);
  const stream = useDocStream("handout");

  // 从讲义“重新生成”时回填全部参数；从教案“生成讲义”时只带上学科、年级、课题等
  const source = useQuery({
    queryKey: ["teacher", "document", fromId],
    enabled: Boolean(fromId),
    queryFn: async () => unwrap(await api.GET("/api/teacher/documents/{doc_id}", { params: { path: { doc_id: fromId! } } })),
  });
  useEffect(() => {
    const doc = source.data;
    if (!doc?.params) return;
    if (doc.doc_type === "handout") {
      form.setFieldsValue(doc.params as HandoutIn);
    } else {
      const { subject, grade, textbook, topic, use_library, resource_ids } = doc.params;
      form.setFieldsValue({ subject, grade, textbook, topic, use_library, resource_ids });
    }
  }, [source.data, form]);

  const regenerating = source.data?.doc_type === "handout";

  return (
    <>
      <PageHead title={regenerating ? "重新生成讲义" : "AI 生成学生讲义"} />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card>
            <Spin spinning={source.isLoading}>
              <Form form={form} layout="vertical" initialValues={DEFAULTS} onFinish={stream.generate} disabled={stream.streaming}>
                <Form.Item name="kind" label="讲义类型" extra={KIND_HINT[kind ?? "课堂讲义"]}>
                  <Radio.Group optionType="button" options={HANDOUT_KINDS.map((k) => ({ value: k, label: k }))} />
                </Form.Item>
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
                <Form.Item
                  name="topic"
                  label={kind === "复习讲义" ? "复习范围" : "课题"}
                  rules={[{ required: true, whitespace: true, message: "请填写课题或复习范围" }]}
                >
                  <Input maxLength={100} placeholder={kind === "复习讲义" ? "例如：第一章 有理数" : "例如：1.2.4 绝对值"} />
                </Form.Item>
                <Form.Item name="textbook" label="教材版本" rules={[{ required: true, whitespace: true }]}>
                  <AutoComplete options={TEXTBOOKS.map((t) => ({ value: t }))} maxLength={30} />
                </Form.Item>
                <Form.Item name="requirements" label="补充要求（选填）">
                  <Input.TextArea rows={3} maxLength={1000} showCount placeholder="例如：学生基础一般，例题由浅入深；多配几道易错题" />
                </Form.Item>
                <LibraryField subject={subject} enabled={useLibrary !== false} hint="按课题检索相关内容，讲义里标注出处" />
                <ReferenceField extra="粘贴教材原文、教案或学案，AI 会以它为准，减少编造" />
                <Button type="primary" htmlType="submit" block size="large" icon={<ThunderboltOutlined />} loading={stream.streaming}>
                  {stream.streaming ? "正在生成…" : "生成讲义"}
                </Button>
              </Form>
            </Spin>
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <PreviewCard stream={stream} idleHint="填好左边的信息，点击“生成讲义”" />
        </Col>
      </Row>
    </>
  );
}
