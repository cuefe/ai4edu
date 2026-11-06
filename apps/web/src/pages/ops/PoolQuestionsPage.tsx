import { ArrowLeftOutlined, CheckCircleOutlined, CheckOutlined, CloseOutlined, EditOutlined, ExclamationCircleOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Collapse, Empty, Form, Input, Modal, Pagination, Popconfirm, Segmented, Select, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";

type Question = Schemas["PoolQuestionOut"];

const LETTERS = "ABCDEF";
const PAGE_SIZE = 20;
const STATUS: Record<string, { color: string; label: string }> = {
  checked: { color: "success", label: "校验一致" },
  disputed: { color: "error", label: "答案有分歧" },
  unchecked: { color: "warning", label: "未能校验" },
  approved: { color: "blue", label: "已通过" },
  rejected: { color: "default", label: "已驳回" },
};

function CheckPanel({ q }: { q: Question }) {
  const c = q.check_result as { verdict?: string; solver_answer?: string; solver_work?: string; reason?: string } | null;
  if (!c) return null;
  const work = c.solver_work ? (
    <Collapse ghost size="small" style={{ marginInline: -16, marginBottom: -8 }} items={[{ key: "work", label: "查看独立解答过程", children: <MarkdownView text={c.solver_work} /> }]} />
  ) : null;
  if (c.verdict === "agree") {
    return (
      <div className="q-check">
        <Typography.Text type="success">
          <CheckCircleOutlined /> 独立解答的答案和参考答案一致
        </Typography.Text>
        {work}
      </div>
    );
  }
  return (
    <Alert
      type={c.verdict === "disagree" ? "error" : "warning"}
      showIcon
      icon={<ExclamationCircleOutlined />}
      style={{ marginTop: 8 }}
      title={
        c.verdict === "disagree" ? (
          <>
            答案有分歧
            {c.solver_answer && (
              <>
                ：独立解出 <MarkdownView text={c.solver_answer} inline />
              </>
            )}
          </>
        ) : (
          "没能自动校验，请人工核对"
        )
      }
      description={
        <>
          {c.reason && <MarkdownView text={c.reason} />}
          {work}
        </>
      }
    />
  );
}

function EditModal({ question, onClose, onSaved }: { question: Question | null; onClose: () => void; onSaved: () => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  useEffect(() => {
    if (question) form.setFieldsValue({ ...question, options: question.options.join("\n") });
  }, [question, form]);
  const save = useMutation({
    mutationFn: async (v: { difficulty: Question["difficulty"]; stem: string; options?: string; answer: string; analysis?: string }) =>
      unwrap(
        await api.PUT("/api/courses/questions/{qid}", {
          params: { path: { qid: question!.id } },
          body: {
            qtype: question!.qtype as Schemas["PoolQuestionIn"]["qtype"],
            difficulty: v.difficulty as Schemas["PoolQuestionIn"]["difficulty"],
            stem: v.stem,
            options: (v.options ?? "").split("\n").map((o) => o.trim()).filter(Boolean),
            answer: v.answer,
            analysis: v.analysis ?? "",
          },
        }),
      ),
    onSuccess: () => {
      message.success("已保存");
      onSaved();
      onClose();
    },
    onError: (e) => message.error(e.message),
  });
  return (
    <Modal title={`修改题目（${question?.qtype ?? ""}）`} open={Boolean(question)} onCancel={onClose} onOk={() => form.submit()} okButtonProps={{ loading: save.isPending }} destroyOnHidden width={720}>
      <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
        <Form.Item name="difficulty" label="难度">
          <Select options={["容易", "中等", "较难"].map((d) => ({ value: d, label: d }))} style={{ width: 120 }} />
        </Form.Item>
        <Form.Item name="stem" label="题干" extra="公式用 $...$" rules={[{ required: true, whitespace: true, message: "请填写题干" }]}>
          <Input.TextArea rows={3} maxLength={5000} />
        </Form.Item>
        {question && question.options.length > 0 && (
          <Form.Item name="options" label="选项（一行一个）">
            <Input.TextArea rows={4} />
          </Form.Item>
        )}
        <Form.Item name="answer" label="答案" extra={question?.qtype === "单选题" ? "写选项字母" : "多个空用“；”隔开"} rules={[{ required: true, whitespace: true, message: "请填写答案" }]}>
          <Input.TextArea rows={2} maxLength={2000} />
        </Form.Item>
        <Form.Item name="analysis" label="解析">
          <Input.TextArea rows={5} maxLength={5000} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function QuestionCard({ q, onEdit, onChanged }: { q: Question; onEdit: () => void; onChanged: () => void }) {
  const { message } = App.useApp();
  const act = useMutation({
    mutationFn: async (action: "approve" | "reject") => {
      const params = { params: { path: { qid: q.id } } };
      if (action === "approve") return unwrap(await api.POST("/api/courses/questions/{qid}/approve", params));
      return unwrap(await api.POST("/api/courses/questions/{qid}/reject", params));
    },
    onSuccess: () => onChanged(),
    onError: (e) => message.error(e.message),
  });
  const meta = STATUS[q.status];
  return (
    <Card size="small" className={q.status === "disputed" ? "q-card q-disputed" : "q-card"} style={{ marginBottom: 12 }}>
      <Space size={[4, 4]} wrap style={{ marginBottom: 8 }}>
        <Tag>{q.section_no}</Tag>
        <Tag>{q.qtype}</Tag>
        <Tag>{q.difficulty}</Tag>
        {q.knowledge_points.map((k) => (
          <Tag key={k} color="geekblue">
            {k}
          </Tag>
        ))}
        {meta && <Tag color={meta.color}>{q.auto_approved ? "自动通过" : meta.label}</Tag>}
        {q.source === "textbook" ? <Tag color="cyan">{q.source_ref || "改编自课本"}</Tag> : <Tag>原创</Tag>}
        {q.edited && <Tag color="purple">人工改过</Tag>}
      </Space>
      <MarkdownView text={q.stem} />
      {q.options.length > 0 && (
        <div className="q-options">
          {q.options.map((o, i) => (
            <div key={i} className={q.answer.includes(LETTERS[i]) ? "q-option q-correct" : "q-option"}>
              {LETTERS[i]}. <MarkdownView text={o} inline />
            </div>
          ))}
        </div>
      )}
      <div className="q-answer">
        <Typography.Text strong>答案：</Typography.Text>
        <MarkdownView text={q.answer} inline />
      </div>
      {q.analysis && <Collapse ghost size="small" style={{ marginInline: -16 }} items={[{ key: "a", label: "解析", children: <MarkdownView text={q.analysis} /> }]} />}
      {q.warnings.length > 0 && <Alert type="warning" showIcon title={q.warnings.join("；")} style={{ marginTop: 8 }} />}
      <CheckPanel q={q} />
      <Space wrap style={{ marginTop: 12 }}>
        {q.status !== "approved" && (
          <Button type="primary" size="small" icon={<CheckOutlined />} loading={act.isPending} onClick={() => act.mutate("approve")}>
            通过
          </Button>
        )}
        <Button size="small" icon={<EditOutlined />} onClick={onEdit}>
          修改
        </Button>
        {q.status !== "rejected" && (
          <Button size="small" icon={<CloseOutlined />} loading={act.isPending} onClick={() => act.mutate("reject")}>
            驳回
          </Button>
        )}
      </Space>
    </Card>
  );
}

/** 周测题库的审核：题目用命令行生成和导入（pool-gen、pool-import），审核通过后才会进周测。 */
export function PoolQuestionsPage() {
  const { bookId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [status, setStatus] = useState("pending");
  const [section, setSection] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Question | null>(null);
  const book = useQuery({
    queryKey: ["courses", bookId],
    queryFn: async () => unwrap(await api.GET("/api/courses/{book_id}", { params: { path: { book_id: bookId } } })),
  });
  const list = useQuery({
    queryKey: ["pool", bookId, status, section, page],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/courses/{book_id}/questions", {
          params: { path: { book_id: bookId }, query: { status, section_id: section, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE } },
        }),
      ),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["pool", bookId] });
  const approveChecked = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/courses/{book_id}/questions/approve-checked", { params: { path: { book_id: bookId } }, body: { section_id: section ?? null } })),
    onSuccess: (r) => {
      message.success(`已通过 ${r.count} 道`);
      refresh();
    },
    onError: (e) => message.error(e.message),
  });
  const counts = list.data?.counts ?? {};
  const pending = (counts.checked ?? 0) + (counts.disputed ?? 0) + (counts.unchecked ?? 0);
  const sections = (book.data?.chapters ?? []).flatMap((c) => c.sections);

  return (
    <>
      <div className="page-head">
        <Space>
          <Button type="text" icon={<ArrowLeftOutlined />} aria-label="返回" onClick={() => navigate("/ops/courses")} />
          <Typography.Title level={4} style={{ margin: 0 }}>
            {book.data ? `${book.data.subject} ${book.data.title} 题库` : "题库"}
          </Typography.Title>
        </Space>
      </div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="只有已通过的题才会进周测。校验一致的题导入时自动通过；有分歧、没校验的题要在这里逐题看。发现错题可以驳回，之后不会再进卷，已经发出去的卷子不受影响。"
      />
      <Space wrap style={{ marginBottom: 16 }}>
        <Segmented
          value={status}
          onChange={(v) => {
            setStatus(String(v));
            setPage(1);
          }}
          options={[
            { value: "pending", label: `待审核 ${pending}` },
            { value: "approved", label: `已通过 ${counts.approved ?? 0}` },
            { value: "rejected", label: `已驳回 ${counts.rejected ?? 0}` },
          ]}
        />
        <Select
          allowClear
          placeholder="全部的节"
          style={{ width: 260 }}
          value={section}
          onChange={(v) => {
            setSection(v);
            setPage(1);
          }}
          options={sections.map((s) => ({ value: s.id, label: `${s.no} ${s.title}` }))}
        />
        {(counts.checked ?? 0) > 0 && (
          <Popconfirm title={`把 ${counts.checked} 道校验一致的题一次通过？`} description="有分歧和没校验的题还要逐题看" onConfirm={() => approveChecked.mutate()}>
            <Button icon={<CheckOutlined />} loading={approveChecked.isPending}>
              通过校验一致的题（{counts.checked}）
            </Button>
          </Popconfirm>
        )}
      </Space>
      <Spin spinning={list.isLoading}>
        {list.data?.items.length === 0 && <Empty description={status === "pending" ? "没有待审核的题。题目用命令行 pool-gen、pool-import 生成和导入" : "这里还没有题"} />}
        {list.data?.items.map((q) => (
          <QuestionCard key={q.id} q={q} onEdit={() => setEditing(q)} onChanged={refresh} />
        ))}
      </Spin>
      {(list.data?.total ?? 0) > PAGE_SIZE && <Pagination current={page} pageSize={PAGE_SIZE} total={list.data?.total} onChange={setPage} showSizeChanger={false} style={{ marginTop: 16 }} />}
      <EditModal question={editing} onClose={() => setEditing(null)} onSaved={refresh} />
    </>
  );
}
