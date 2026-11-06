import { SendOutlined, SettingOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Empty, Form, Modal, Popconfirm, Row, Select, Space, Spin, Statistic, Switch, Tag, TreeSelect, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { PageHead } from "@/components/PageHead";

type Row = Schemas["ClassWeeklyOut"];

function ProgressModal({ row, onClose }: { row: Row | null; onClose: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<{ book_id: string; section_ids: string[]; enabled: boolean }>();
  const bookId = Form.useWatch("book_id", form);
  const catalog = useQuery({ queryKey: ["courses"], queryFn: async () => unwrap(await api.GET("/api/courses")), enabled: Boolean(row) });
  const books = (catalog.data?.books ?? []).filter((b) => !row?.subject || b.subject === row.subject);
  const sections = useQuery({
    queryKey: ["teacher", "weekly", "sections", bookId],
    enabled: Boolean(bookId),
    queryFn: async () => unwrap(await api.GET("/api/teacher/weekly/books/{book_id}/sections", { params: { path: { book_id: bookId } } })),
  });
  useEffect(() => {
    if (!row) return;
    form.setFieldsValue({
      book_id: row.progress?.book_id,
      section_ids: row.progress?.section_ids ?? [],
      enabled: row.progress?.enabled ?? true,
    });
  }, [row, form]);
  const tree = useMemo(() => {
    const chapters = new Map<string, { title: string; value: string; key: string; children: { title: string; value: string; key: string }[] }>();
    for (const s of sections.data ?? []) {
      const key = `chapter-${s.chapter_no}`;
      if (!chapters.has(key)) chapters.set(key, { title: `第 ${s.chapter_no} 章 ${s.chapter_title}`, value: key, key, children: [] });
      chapters.get(key)!.children.push({ title: `${s.no} ${s.title}（可用 ${s.approved_count} 题）`, value: s.id, key: s.id });
    }
    return [...chapters.values()];
  }, [sections.data]);
  const save = useMutation({
    mutationFn: async (v: { book_id: string; section_ids: string[]; enabled: boolean }) =>
      unwrap(await api.PUT("/api/teacher/weekly/classes/{klass_id}/progress", { params: { path: { klass_id: row!.klass_id } }, body: v })),
    onSuccess: () => {
      message.success("进度已保存");
      qc.invalidateQueries({ queryKey: ["teacher", "weekly"] });
      onClose();
    },
    onError: (e) => message.error(e.message),
  });
  return (
    <Modal title={row ? `${row.class_name} 的教学进度` : ""} open={Boolean(row)} onCancel={onClose} onOk={() => form.submit()} okButtonProps={{ loading: save.isPending }} okText="保存" destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
        <Form.Item name="book_id" label="教材" rules={[{ required: true, message: "请选择教材" }]}>
          <Select
            placeholder="选择这学期用的教材"
            loading={catalog.isLoading}
            onChange={() => form.setFieldValue("section_ids", [])}
            options={books.map((b) => ({ value: b.id, label: `${b.subject} · ${b.grade} ${b.title}（${b.edition}）` }))}
            notFoundContent={<Empty description="这门课还没有发布的教材" />}
          />
        </Form.Item>
        <Form.Item name="section_ids" label="这周教的节" extra="周测约 70% 考这些内容，其余考学生学过的薄弱点和错题同类题。排在所选节后面的内容不会考。" rules={[{ required: true, message: "请选择这周教的节" }]}>
          <TreeSelect treeData={tree} treeCheckable showCheckedStrategy={TreeSelect.SHOW_CHILD} placeholder={bookId ? "选择节" : "先选教材"} disabled={!bookId} loading={sections.isLoading} treeDefaultExpandAll style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="enabled" label="每周自动发周测" valuePropName="checked" extra="每周五下午 4 点发卷，周日晚上 10 点截止">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function ClassCard({ row, onSetting }: { row: Row; onSetting: () => void }) {
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const p = row.progress;
  const issue = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/teacher/weekly/classes/{klass_id}/issue", { params: { path: { klass_id: row.klass_id }, query: { subject: p!.subject } } })),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["teacher", "weekly"] });
      const notes = [
        r.short.length > 0 && `${r.short.join("、")} 因为题库不够没发成`,
        r.partial.length > 0 && `${r.partial.join("、")} 的卷子题目偏少`,
        r.stale_progress && "这周的进度还没更新，用的是上次设置的节",
      ].filter(Boolean);
      if (notes.length) modal.warning({ title: `发出 ${r.created} 份`, content: notes.join("；") });
      else message.success(r.created ? `已发出 ${r.created} 份` : "这周都发过了");
    },
    onError: (e) => message.error(e.message),
  });
  const w = row.week;
  return (
    <Card
      title={
        <Space wrap>
          {row.class_name}
          {row.subject && <Tag>{row.subject}</Tag>}
          {p && !p.enabled && <Tag>已停用</Tag>}
        </Space>
      }
      extra={<Typography.Text type="secondary">{row.student_count} 名学生</Typography.Text>}
      style={{ marginBottom: 16 }}
    >
      {p ? (
        <div style={{ marginBottom: 12 }}>
          <Typography.Text type="secondary">{p.book_title} · 这周教：</Typography.Text>
          <Typography.Text>{p.section_labels.join("、")}</Typography.Text>
          {!p.up_to_date && (
            <Tag color="orange" style={{ marginInlineStart: 8 }}>
              这周还没更新
            </Tag>
          )}
        </div>
      ) : (
        <Alert type="info" showIcon title="先设置教学进度，才会给这个班发周测" style={{ marginBottom: 12 }} />
      )}
      {w && (
        <Row gutter={[16, 16]} style={{ marginBottom: 12 }}>
          <Col xs={12} md={6}>
            <Statistic title="这周已发" value={w.issued} suffix="份" />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="已提交" value={w.submitted} suffix={`/ ${w.issued}`} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="平均得分率" value={w.avg_percent ?? "—"} suffix={w.avg_percent != null ? "%" : undefined} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="待确认批改" value={w.pending_review} styles={{ content: { color: w.pending_review ? "#fa8c16" : undefined } }} />
          </Col>
        </Row>
      )}
      <Space wrap>
        <Button icon={<SettingOutlined />} onClick={onSetting}>
          {p ? "更新进度" : "设置进度"}
        </Button>
        {p && (
          <Popconfirm title="现在给全班发这周的周测？" description="已经发过的学生不会重复发" onConfirm={() => issue.mutate()}>
            <Button type="primary" icon={<SendOutlined />} loading={issue.isPending}>
              现在发卷
            </Button>
          </Popconfirm>
        )}
        {p && <Button onClick={() => navigate(`/teacher/weekly/${row.klass_id}?subject=${encodeURIComponent(p.subject)}`)}>查看成绩</Button>}
      </Space>
    </Card>
  );
}

export function WeeklyPage() {
  const [setting, setSetting] = useState<Row | null>(null);
  const list = useQuery({ queryKey: ["teacher", "weekly"], queryFn: async () => unwrap(await api.GET("/api/teacher/weekly")) });
  return (
    <>
      <PageHead title="周测" />
      <Typography.Paragraph type="secondary">
        系统按教学进度给每个学生组一份不同的卷子。这周的成绩决定下周的难度：85 分及以上升一档，低于 60 分降一档。解答题由 AI 先批改，你确认后学生才能看到分数。
      </Typography.Paragraph>
      <Spin spinning={list.isLoading}>
        {list.data?.length === 0 && <Empty description="你还没有任教的班级" />}
        {list.data?.map((row) => (
          <ClassCard key={`${row.klass_id}-${row.subject}`} row={row} onSetting={() => setSetting(row)} />
        ))}
      </Spin>
      <ProgressModal row={setting} onClose={() => setSetting(null)} />
    </>
  );
}
