import { DeleteOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Col, Empty, Form, Input, InputNumber, Modal, Popconfirm, Radio, Row, Select, Table, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { GRADES, SUBJECTS } from "./lessonPlanOptions";

type ReciteIn = Schemas["ReciteIn"];
type FormValues = ReciteIn & { source: "doc" | "text" };

const QUERY_KEY = ["teacher", "recite-decks"];

/** 生成好的讲义和教案，作为抽背诵点的材料。 */
function useReadyDocuments() {
  const handouts = useQuery({
    queryKey: ["teacher", "documents", "handout"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/documents", { params: { query: { doc_type: "handout" } } })),
  });
  const plans = useQuery({
    queryKey: ["teacher", "documents", "lesson_plan"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/documents", { params: { query: { doc_type: "lesson_plan" } } })),
  });
  const ready =(docs: Schemas["DocumentBrief"][] | undefined) => (docs ?? []).filter((d) => d.status === "ready");
  return {
    loading: handouts.isLoading || plans.isLoading,
    docs: [...ready(handouts.data), ...ready(plans.data)],
    options: [
      { label: "讲义", options: ready(handouts.data).map((d) => ({ value: d.id, label: d.title })) },
      { label: "教案", options: ready(plans.data).map((d) => ({ value: d.id, label: d.title })) },
    ].filter((g) => g.options.length > 0),
  };
}

function GenerateModal({ open, fromId, onClose }: { open: boolean; fromId: string | null; onClose: () => void }) {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const source = Form.useWatch("source", form);
  const { docs, options, loading } = useReadyDocuments();

  const generate = useMutation({
    mutationFn: async ({ source, ...values }: FormValues) => {
      const body = source === "doc" ? { ...values, text: null } : { ...values, doc_id: null };
      return unwrap(await api.POST("/api/teacher/recite-decks/generate", { body }));
    },
    onSuccess: (deck) => {
      message.success(`整理出 ${deck.card_count} 张卡片，可以直接修改`);
      navigate(`/teacher/recite/${deck.id}`);
    },
    onError: (e) => message.error(e.message),
  });

  // 选了讲义或教案：带出学科、年级，标题默认“xxx 必背”
  const pickDoc = (doc: Schemas["DocumentBrief"] | undefined) => {
    if (!doc) return;
    form.setFieldsValue({
      doc_id: doc.id,
      title: `${doc.title} 必背`.slice(0, 100),
      ...(doc.subject ? { subject: doc.subject as ReciteIn["subject"] } : {}),
      ...(doc.grade ? { grade: doc.grade as ReciteIn["grade"] } : {}),
    });
  };

  // 从讲义、教案的编辑页跳过来：预先选好那份文档
  const fromDoc = docs.find((d) => d.id === fromId);
  const applied = useRef(false);
  useEffect(() => {
    if (open && fromDoc && !applied.current) {
      applied.current = true; // 只带入一次，之后列表刷新不覆盖老师改过的内容
      form.setFieldsValue({ source: "doc" });
      pickDoc(fromDoc);
    }
  }, [open, fromDoc]);

  return (
    <Modal
      title="AI 抽取背诵点"
      open={open}
      onCancel={() => !generate.isPending && onClose()}
      okText={generate.isPending ? "正在整理…" : "开始整理"}
      okButtonProps={{ icon: <ThunderboltOutlined />, loading: generate.isPending }}
      cancelButtonProps={{ disabled: generate.isPending }}
      onOk={() => form.submit()}
      mask={{ closable: false }}
      destroyOnHidden
      width={600}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ source: "doc", subject: "数学", grade: "七年级上册", max_cards: 20 }}
        onFinish={(v) => generate.mutate(v)}
        disabled={generate.isPending}
        preserve={false}
      >
        <Form.Item name="source" label="从哪里整理">
          <Radio.Group
            optionType="button"
            options={[
              { value: "doc", label: "我的讲义或教案" },
              { value: "text", label: "粘贴内容" },
            ]}
          />
        </Form.Item>
        {source === "text" ? (
          <Form.Item name="text" rules={[{ required: true, whitespace: true, message: "请粘贴要整理的内容" }]}>
            <Input.TextArea rows={8} maxLength={20000} showCount placeholder="粘贴教材原文、知识点总结、单词表等" />
          </Form.Item>
        ) : (
          <Form.Item
            name="doc_id"
            rules={[{ required: true, message: "请选择一份讲义或教案" }]}
            extra={
              !loading && options.length === 0 ? (
                <>
                  还没有生成好的讲义或教案，<Link to="/teacher/handouts/new">先生成一份讲义</Link>，或者改用粘贴内容
                </>
              ) : (
                "会读取你修改后的最新内容"
              )
            }
          >
            <Select
              options={options}
              loading={loading}
              showSearch={{ optionFilterProp: "label" }}
              placeholder="选择讲义或教案"
              onChange={(id: string) => pickDoc(docs.find((d) => d.id === id))}
            />
          </Form.Item>
        )}
        <Form.Item name="title" label="卡片组名称" rules={[{ required: true, whitespace: true, message: "请填写名称" }]}>
          <Input maxLength={100} placeholder="例如：1.2.4 绝对值 必背" />
        </Form.Item>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="subject" label="学科">
              <Select options={SUBJECTS.map((s) => ({ value: s, label: s }))} />
            </Form.Item>
          </Col>
          <Col span={10}>
            <Form.Item name="grade" label="年级">
              <Select options={GRADES.map((g) => ({ value: g, label: g }))} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="max_cards" label="最多几张">
              <InputNumber min={5} max={50} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="requirements" label="补充要求（选填）" style={{ marginBottom: 8 }}>
          <Input maxLength={500} placeholder="例如：只要定义和公式；单词只要四会词" />
        </Form.Item>
        {generate.isPending && (
          <Alert type="info" showIcon title="AI 正在整理背诵点，大约需要半分钟，请不要关闭窗口" style={{ marginTop: 16 }} />
        )}
      </Form>
    </Modal>
  );
}

export function RecitePage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [params, setParams] = useSearchParams();
  const fromId = params.get("from");
  const [open, setOpen] = useState(Boolean(fromId));
  const decks = useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () => unwrap(await api.GET("/api/teacher/recite-decks")),
  });
  const remove = useMutation({
    mutationFn: async (id: string) => unwrap(await api.DELETE("/api/teacher/recite-decks/{deck_id}", { params: { path: { deck_id: id } } })),
    onSuccess: () => {
      message.success("已删除");
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (e) => message.error(e.message),
  });

  return (
    <>
      <PageHead
        title="背诵卡片"
        extra={
          <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => setOpen(true)}>
            AI 抽取背诵点
          </Button>
        }
      />
      <Typography.Paragraph type="secondary">
        从讲义、教案或粘贴的材料里整理出必背内容，做成问答卡和挖空卡。下一阶段可以布置给学生，学生端按遗忘规律安排复习。
      </Typography.Paragraph>
      <Table
        rowKey="id"
        loading={decks.isLoading}
        dataSource={decks.data}
        scroll={{ x: 640 }}
        locale={{ emptyText: <Empty description="还没有背诵卡片，可以从讲义里一键抽取" /> }}
        columns={[
          { title: "名称", dataIndex: "title", render: (t: string, d) => <Link to={`/teacher/recite/${d.id}`}>{t}</Link> },
          { title: "学科", dataIndex: "subject", width: 80 },
          { title: "年级", dataIndex: "grade", width: 120 },
          { title: "卡片", dataIndex: "card_count", width: 80, render: (n: number) => `${n} 张` },
          { title: "更新时间", dataIndex: "updated_at", width: 140, render: (t: string) => dayjs(t).format("MM-DD HH:mm") },
          {
            title: "操作",
            width: 90,
            render: (_, d) => (
              <Popconfirm title={`删除「${d.title}」？`} onConfirm={() => remove.mutate(d.id)}>
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            ),
          },
        ]}
      />
      <GenerateModal
        open={open}
        fromId={fromId}
        onClose={() => {
          setOpen(false);
          if (fromId) setParams({}, { replace: true });
        }}
      />
    </>
  );
}
