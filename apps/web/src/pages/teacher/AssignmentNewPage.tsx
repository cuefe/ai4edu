import { ArrowDownOutlined, ArrowUpOutlined, BookOutlined, CreditCardOutlined, DeleteOutlined, FileTextOutlined, SendOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";
import { PageHead } from "@/components/PageHead";
import { SUBJECTS } from "./lessonPlanOptions";
import { QTYPES, type QuestionOut } from "./questionUi";

type Item = { key: string; item_type: "question" | "document" | "recite"; ref_id: string; score: number; label: string; detail?: string };
type FormValues = {
  title: string;
  subject: "数学" | "英语";
  class_ids: string[];
  publish: "now" | "later";
  publish_at?: Dayjs;
  due_at?: Dayjs;
  answer_release: "submit" | "due";
  allow_ai: boolean;
  note?: string;
};

const DEFAULT_SCORE: Record<string, number> = { 解答题: 10 };
const TYPE_TAG = {
  question: { color: "blue", label: "题目" },
  document: { color: "green", label: "讲义阅读" },
  recite: { color: "purple", label: "背诵" },
} as const;

function QuestionPicker({
  open,
  subject,
  picked,
  onClose,
  onPick,
}: {
  open: boolean;
  subject: string;
  picked: Set<string>;
  onClose: () => void;
  onPick: (qs: QuestionOut[]) => void;
}) {
  const [page, setPage] = useState(1);
  const [qtype, setQtype] = useState<string>();
  const [keyword, setKeyword] = useState<string>();
  const [selected, setSelected] = useState<Map<string, QuestionOut>>(new Map());
  const list = useQuery({
    queryKey: ["teacher", "questions", "picker", subject, qtype, keyword, page],
    enabled: open,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/teacher/questions", {
          params: { query: { view: "bank", subject, qtype, keyword, page, page_size: 8 } },
        }),
      ),
  });
  return (
    <Modal
      title="从题库选题"
      open={open}
      width={760}
      onCancel={onClose}
      okText={`加入 ${selected.size} 道题`}
      okButtonProps={{ disabled: selected.size === 0 }}
      onOk={() => {
        onPick([...selected.values()]);
        setSelected(new Map());
      }}
      destroyOnHidden
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="题型" style={{ width: 110 }} options={QTYPES.map((t) => ({ value: t, label: t }))} onChange={(v) => { setQtype(v); setPage(1); }} />
        <Input.Search allowClear placeholder="搜题干、知识点" style={{ width: 240 }} onSearch={(v) => { setKeyword(v.trim() || undefined); setPage(1); }} />
        <Typography.Text type="secondary">只列出{subject}机构题库里已入库的题</Typography.Text>
      </Space>
      <Spin spinning={list.isLoading}>
        {list.data?.items.length === 0 && <Empty description="题库里还没有符合条件的题，可以先去「题库」出题或录题" />}
        {list.data?.items.map((q) => {
          const already = picked.has(q.id);
          return (
            <div key={q.id} className="pick-row">
              <Checkbox
                disabled={already}
                checked={already || selected.has(q.id)}
                onChange={(e) =>
                  setSelected((m) => {
                    const next = new Map(m);
                    if (e.target.checked) next.set(q.id, q);
                    else next.delete(q.id);
                    return next;
                  })
                }
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <Space size={4} wrap>
                  <Tag>{q.qtype}</Tag>
                  <Tag>{q.difficulty}</Tag>
                  {q.knowledge_points.map((k) => (
                    <Tag key={k} color="geekblue">
                      {k}
                    </Tag>
                  ))}
                  {already && <Typography.Text type="secondary">已加入</Typography.Text>}
                </Space>
                <MarkdownView text={q.stem} />
              </div>
            </div>
          );
        })}
      </Spin>
      {(list.data?.total ?? 0) > 8 && <Pagination size="small" align="end" current={page} pageSize={8} total={list.data?.total} onChange={setPage} />}
    </Modal>
  );
}

export function AssignmentNewPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const subject = Form.useWatch("subject", form) ?? "数学";
  const publish = Form.useWatch("publish", form);
  const [items, setItems] = useState<Item[]>([]);
  const [picking, setPicking] = useState(false);

  const classes = useQuery({ queryKey: ["teacher", "classes"], queryFn: async () => unwrap(await api.GET("/api/teacher/classes")) });
  const handouts = useQuery({
    queryKey: ["teacher", "documents", "handout"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/documents", { params: { query: { doc_type: "handout" } } })),
  });
  const decks = useQuery({ queryKey: ["teacher", "recite-decks"], queryFn: async () => unwrap(await api.GET("/api/teacher/recite-decks")) });

  const add = (next: Item[]) => setItems((list) => [...list, ...next.filter((n) => !list.some((x) => x.key === n.key))]);
  const move = (i: number, d: number) =>
    setItems((list) => {
      const next = [...list];
      [next[i], next[i + d]] = [next[i + d], next[i]];
      return next;
    });

  const create = useMutation({
    mutationFn: async (v: FormValues) => {
      const body: Schemas["AssignmentIn"] = {
        title: v.title,
        subject: v.subject,
        class_ids: v.class_ids,
        student_ids: [],
        note: v.note ?? "",
        publish_at: v.publish === "later" && v.publish_at ? v.publish_at.toISOString() : null,
        due_at: v.due_at ? v.due_at.toISOString() : null,
        answer_release: v.answer_release,
        allow_ai: v.allow_ai,
        items: items.map((i) => ({ item_type: i.item_type, ref_id: i.ref_id, score: i.score })),
      };
      return unwrap(await api.POST("/api/teacher/assignments", { body }));
    },
    onSuccess: (a) => {
      message.success(`已布置给 ${a.student_count} 名学生`);
      navigate(`/teacher/assignments/${a.id}`, { replace: true });
    },
    onError: (e) => message.error(e.message),
  });

  const total = items.reduce((s, i) => s + (i.item_type === "question" ? i.score : 0), 0);
  const readyHandouts = (handouts.data ?? []).filter((d) => d.status === "ready");

  return (
    <>
      <PageHead title="布置作业" />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card>
            <Form
              form={form}
              layout="vertical"
              initialValues={{ subject: "数学", class_ids: [], publish: "now", answer_release: "submit", allow_ai: true, due_at: dayjs().add(1, "day").hour(21).minute(0).second(0) }}
              onFinish={(v) => (items.length ? create.mutate(v) : message.warning("请先添加题目、讲义或背诵卡片"))}
            >
              <Form.Item name="title" label="作业名称" rules={[{ required: true, whitespace: true, message: "请填写作业名称" }]}>
                <Input maxLength={200} placeholder="例如：1.2 有理数 课后作业" />
              </Form.Item>
              <Row gutter={12}>
                <Col span={9}>
                  <Form.Item name="subject" label="学科">
                    <Select options={SUBJECTS.map((s) => ({ value: s, label: s }))} />
                  </Form.Item>
                </Col>
                <Col span={15}>
                  <Form.Item name="class_ids" label="布置给" rules={[{ required: true, type: "array", min: 1, message: "请选择班级" }]}>
                    <Select
                      mode="multiple"
                      loading={classes.isLoading}
                      placeholder="选择班级"
                      options={(classes.data ?? []).map((k) => ({ value: k.id, label: `${k.name}（${k.student_count} 人）` }))}
                      notFoundContent="你还没有任教的班级，请联系机构管理员"
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item label="发布时间" style={{ marginBottom: 8 }}>
                <Space wrap>
                  <Form.Item name="publish" noStyle>
                    <Radio.Group optionType="button" options={[{ value: "now", label: "马上发布" }, { value: "later", label: "定时发布" }]} />
                  </Form.Item>
                  {publish === "later" && (
                    <Form.Item name="publish_at" noStyle rules={[{ required: true, message: "请选择发布时间" }]}>
                      <DatePicker showTime={{ format: "HH:mm" }} format="MM-DD HH:mm" disabledDate={(d) => d.isBefore(dayjs(), "day")} />
                    </Form.Item>
                  )}
                </Space>
              </Form.Item>
              <Form.Item name="due_at" label="截止时间" extra="过了截止时间学生仍可以补交，报告里会标出迟交">
                <DatePicker showTime={{ format: "HH:mm" }} format="YYYY-MM-DD HH:mm" disabledDate={(d) => d.isBefore(dayjs(), "day")} style={{ width: 220 }} />
              </Form.Item>
              <Form.Item name="answer_release" label="答案公布">
                <Radio.Group options={[{ value: "submit", label: "学生提交后马上公布" }, { value: "due", label: "截止后统一公布" }]} />
              </Form.Item>
              <Form.Item label="作业中问 AI" extra="开启时 AI 只给思路和提示，不直接给答案；关闭后作业期间学生不能使用问一问">
                <Form.Item name="allow_ai" valuePropName="checked" noStyle>
                  <Switch checkedChildren="允许" unCheckedChildren="不允许" />
                </Form.Item>
              </Form.Item>
              <Form.Item name="note" label="给学生的话（选填）">
                <Input.TextArea rows={2} maxLength={1000} placeholder="例如：先读讲义，再做题；解答题写出过程" />
              </Form.Item>
              <Button type="primary" htmlType="submit" block size="large" icon={<SendOutlined />} loading={create.isPending}>
                布置作业
              </Button>
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <Card
            title={`作业内容（${items.length} 项，题目共 ${total} 分）`}
            extra={
              <Space wrap>
                <Button icon={<BookOutlined />} onClick={() => setPicking(true)}>
                  从题库选题
                </Button>
                <Select
                  placeholder={<><FileTextOutlined /> 加讲义</>}
                  value={null}
                  style={{ width: 150 }}
                  loading={handouts.isLoading}
                  notFoundContent="还没有生成好的讲义"
                  options={readyHandouts.map((d) => ({ value: d.id, label: d.title }))}
                  onChange={(id: string) => {
                    const d = readyHandouts.find((x) => x.id === id);
                    if (d) add([{ key: `document-${id}`, item_type: "document", ref_id: id, score: 0, label: d.title }]);
                  }}
                />
                <Select
                  placeholder={<><CreditCardOutlined /> 加背诵卡片</>}
                  value={null}
                  style={{ width: 160 }}
                  loading={decks.isLoading}
                  notFoundContent="还没有背诵卡片"
                  options={(decks.data ?? []).map((d) => ({ value: d.id, label: `${d.title}（${d.card_count} 张）` }))}
                  onChange={(id: string) => {
                    const d = decks.data?.find((x) => x.id === id);
                    if (d) add([{ key: `recite-${id}`, item_type: "recite", ref_id: id, score: 0, label: d.title, detail: `${d.card_count} 张卡片` }]);
                  }}
                />
              </Space>
            }
          >
            {items.length === 0 && <Empty description="可以加入题库里的题、要读的讲义、要背的卡片" />}
            {items.map((item, i) => (
              <div key={item.key} className="pick-row">
                <Typography.Text strong>{i + 1}.</Typography.Text>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Space size={4} wrap>
                    <Tag color={TYPE_TAG[item.item_type].color}>{TYPE_TAG[item.item_type].label}</Tag>
                    {item.detail && <Typography.Text type="secondary">{item.detail}</Typography.Text>}
                  </Space>
                  {item.item_type === "question" ? <MarkdownView text={item.label} /> : <div>{item.label}</div>}
                </div>
                <Space size={0}>
                  {item.item_type === "question" && (
                    <InputNumber
                      size="small"
                      min={0.5}
                      max={100}
                      step={0.5}
                      value={item.score}
                      suffix="分"
                      style={{ width: 84 }}
                      onChange={(v) => setItems((list) => list.map((x) => (x.key === item.key ? { ...x, score: v ?? x.score } : x)))}
                    />
                  )}
                  <Button type="text" size="small" icon={<ArrowUpOutlined />} disabled={i === 0} onClick={() => move(i, -1)} aria-label="上移" />
                  <Button type="text" size="small" icon={<ArrowDownOutlined />} disabled={i === items.length - 1} onClick={() => move(i, 1)} aria-label="下移" />
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={() => setItems((list) => list.filter((x) => x.key !== item.key))} aria-label="移除" />
                </Space>
              </div>
            ))}
          </Card>
        </Col>
      </Row>
      <QuestionPicker
        open={picking}
        subject={subject}
        picked={new Set(items.filter((i) => i.item_type === "question").map((i) => i.ref_id))}
        onClose={() => setPicking(false)}
        onPick={(qs) => {
          add(
            qs.map((q) => ({
              key: `question-${q.id}`,
              item_type: "question" as const,
              ref_id: q.id,
              score: DEFAULT_SCORE[q.qtype] ?? 5,
              label: q.stem,
              detail: `${q.qtype} · ${q.difficulty}`,
            })),
          );
          setPicking(false);
        }}
      />
    </>
  );
}
