import {
  CheckCircleOutlined,
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Checkbox, Col, Collapse, Form, Input, Modal, Popconfirm, Radio, Row, Select, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect, type ReactNode } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";
import { GRADES, SUBJECTS } from "./lessonPlanOptions";

export type QuestionOut = Schemas["QuestionOut"];
export type QuestionIn = Schemas["QuestionIn"];
export type QuestionGenIn = Schemas["QuestionGenIn"];

export const QTYPES: QuestionIn["qtype"][] = ["单选题", "多选题", "判断题", "填空题", "解答题"];
export const DIFFICULTIES: QuestionIn["difficulty"][] = ["容易", "中等", "较难"];
const CHOICE = new Set(["单选题", "多选题"]);
const LETTERS = "ABCDEF";

export const STATUS_META: Record<string, { color: string; label: string; icon: ReactNode }> = {
  checking: { color: "processing", label: "校验中", icon: <SyncOutlined spin /> },
  checked: { color: "success", label: "校验一致", icon: <CheckCircleOutlined /> },
  disputed: { color: "error", label: "答案有分歧", icon: <ExclamationCircleOutlined /> },
  unchecked: { color: "warning", label: "未能校验", icon: <QuestionCircleOutlined /> },
  approved: { color: "blue", label: "已入库", icon: <CheckOutlined /> },
  rejected: { color: "default", label: "已驳回", icon: <CloseOutlined /> },
};

const METHOD_LABEL: Record<string, string> = { rule: "规则比对", numeric: "数值比对", judge: "模型比对" };
const PENDING = new Set(["checking", "checked", "disputed", "unchecked"]);

/** 题目有改动的接口调用完后，刷新列表、计数和出题进度。 */
export function useInvalidateQuestions() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["teacher", "questions"] });
    qc.invalidateQueries({ queryKey: ["teacher", "question-batch"] });
  };
}

function CheckPanel({ q }: { q: QuestionOut }) {
  const check = q.check;
  if (q.status === "checking") {
    return <Typography.Text type="secondary">推理模型正在独立解题，核对答案…</Typography.Text>;
  }
  if (!check) return null;
  const stale = PENDING.has(q.status) && dayjs(q.updated_at).isAfter(check.created_at);
  const work = check.solver_work ? (
    <Collapse
      ghost
      size="small"
      style={{ marginInline: -16, marginBottom: -8 }}
      items={[{ key: "work", label: "查看独立解答过程", children: <MarkdownView text={check.solver_work} /> }]}
    />
  ) : null;
  const method = METHOD_LABEL[check.method] ? `（${METHOD_LABEL[check.method]}）` : "";
  if (check.verdict === "agree") {
    return (
      <div className="q-check">
        <Typography.Text type="success">
          <CheckCircleOutlined /> 推理模型独立解出的答案和参考答案一致{method}
        </Typography.Text>
        {stale && <Typography.Text type="secondary">　题目在校验后改过，可以重新校验</Typography.Text>}
        {work}
      </div>
    );
  }
  return (
    <Alert
      type={check.verdict === "disagree" ? "error" : "warning"}
      showIcon
      title={
        check.verdict === "disagree" ? (
          <>
            答案有分歧{check.solver_answer ? `：独立解出「${check.solver_answer}」` : ""}
          </>
        ) : (
          "没能自动校验，请人工核对"
        )
      }
      description={
        <>
          <div>{check.reason}</div>
          {stale && <Typography.Text type="secondary">题目在校验后改过，可以重新校验。</Typography.Text>}
          {work}
        </>
      }
      style={{ marginTop: 8 }}
    />
  );
}

/** 一道题：题干、选项、答案解析、校验结果和审核按钮。 */
export function QuestionItem({ q, index, onEdit }: { q: QuestionOut; index?: number; onEdit: (q: QuestionOut) => void }) {
  const { message } = App.useApp();
  const invalidate = useInvalidateQuestions();
  const meta = STATUS_META[q.status];
  const act = useMutation({
    mutationFn: async (action: "approve" | "reject" | "recheck" | "delete") => {
      const params = { params: { path: { qid: q.id } } };
      if (action === "delete") return unwrap(await api.DELETE("/api/teacher/questions/{qid}", params));
      if (action === "approve") return unwrap(await api.POST("/api/teacher/questions/{qid}/approve", params));
      if (action === "reject") return unwrap(await api.POST("/api/teacher/questions/{qid}/reject", params));
      return unwrap(await api.POST("/api/teacher/questions/{qid}/recheck", params));
    },
    onSuccess: (_, action) => {
      message.success({ approve: "已入库", reject: "已驳回", recheck: "已开始重新校验", delete: "已删除" }[action]);
      invalidate();
    },
    onError: (e) => message.error(e.message),
  });
  const answerLetters = CHOICE.has(q.qtype) ? new Set(q.answer) : null;
  const pending = PENDING.has(q.status);
  const busy = q.status === "checking" || act.isPending;

  return (
    <Card size="small" className={q.status === "disputed" ? "q-card q-disputed" : "q-card"}>
      <Space size={[4, 4]} wrap style={{ marginBottom: 8 }}>
        {index !== undefined && <Typography.Text strong>{index + 1}.</Typography.Text>}
        <Tag>{q.qtype}</Tag>
        <Tag>{q.difficulty}</Tag>
        {q.knowledge_points.map((k) => (
          <Tag key={k} color="geekblue">
            {k}
          </Tag>
        ))}
        {meta && (
          <Tag color={meta.color} icon={meta.icon}>
            {meta.label}
          </Tag>
        )}
        {q.source === "manual" && <Tag>手动录入</Tag>}
        {q.edited && <Tag color="purple">老师改过</Tag>}
        {!q.mine && <Typography.Text type="secondary">{q.owner_name} 出的题</Typography.Text>}
      </Space>
      <MarkdownView text={q.stem} />
      {q.options.length > 0 && (
        <div className="q-options">
          {q.options.map((o, i) => (
            <div key={i} className={answerLetters?.has(LETTERS[i]) ? "q-option q-correct" : "q-option"}>
              {LETTERS[i]}. <MarkdownView text={o} inline />
            </div>
          ))}
        </div>
      )}
      <div className="q-answer">
        <Typography.Text strong>答案：</Typography.Text>
        <MarkdownView text={q.answer} inline />
      </div>
      {q.analysis && (
        <Collapse
          ghost
          size="small"
          style={{ marginInline: -16 }}
          items={[{ key: "analysis", label: "解析", children: <MarkdownView text={q.analysis} /> }]}
        />
      )}
      {q.warnings.length > 0 && <Alert type="warning" showIcon title={q.warnings.join("；")} style={{ marginTop: 8 }} />}
      <CheckPanel q={q} />
      {q.mine && (
        <Space wrap style={{ marginTop: 12 }}>
          {q.status !== "approved" && (
            <Button type="primary" size="small" icon={<CheckOutlined />} disabled={busy} onClick={() => act.mutate("approve")}>
              通过入库
            </Button>
          )}
          <Button size="small" icon={<EditOutlined />} disabled={busy} onClick={() => onEdit(q)}>
            修改
          </Button>
          {pending && (
            <Button size="small" icon={<CloseOutlined />} disabled={busy} onClick={() => act.mutate("reject")}>
              驳回
            </Button>
          )}
          {(pending || q.status === "rejected") && (
            <Button size="small" icon={<ReloadOutlined />} disabled={busy} onClick={() => act.mutate("recheck")}>
              重新校验
            </Button>
          )}
          {!pending && (
            <Popconfirm title="删除这道题？" onConfirm={() => act.mutate("delete")}>
              <Button size="small" danger icon={<DeleteOutlined />} disabled={busy}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      )}
    </Card>
  );
}

// 选择题的答案用单选框（single）或复选框（letters）选，其他题型直接填 answer
type EditForm = Omit<QuestionIn, "answer"> & { answer?: string; single?: string; letters?: string[] };

/** 修改或手动录入题目。question 为 null 时关闭；没有 id 时是新建。 */
export function QuestionEditModal({ question, onClose }: { question: Partial<QuestionOut> | null; onClose: () => void }) {
  const { message } = App.useApp();
  const invalidate = useInvalidateQuestions();
  const [form] = Form.useForm<EditForm>();
  const qtype = Form.useWatch("qtype", form);
  const stem = Form.useWatch("stem", form) ?? "";
  const options: string[] = Form.useWatch("options", form) ?? [];

  useEffect(() => {
    if (!question) return;
    const qt = (question.qtype ?? "单选题") as QuestionIn["qtype"];
    form.setFieldsValue({
      subject: (question.subject ?? "数学") as QuestionIn["subject"],
      grade: (question.grade ?? null) as QuestionIn["grade"],
      qtype: qt,
      difficulty: (question.difficulty ?? "中等") as QuestionIn["difficulty"],
      stem: question.stem ?? "",
      options: question.options?.length ? question.options : ["", "", "", ""],
      answer: question.answer ?? "",
      single: qt === "单选题" ? question.answer : undefined,
      letters: qt === "多选题" ? (question.answer ?? "").split("") : [],
      analysis: question.analysis ?? "",
      knowledge_points: question.knowledge_points ?? [],
    });
  }, [question, form]);

  const save = useMutation({
    mutationFn: async ({ single, letters, ...v }: EditForm) => {
      const choice = CHOICE.has(v.qtype);
      const answer = v.qtype === "单选题" ? (single ?? "") : v.qtype === "多选题" ? [...(letters ?? [])].sort().join("") : v.answer;
      const body: QuestionIn = {
        ...v,
        options: choice ? (v.options ?? []).map((o) => o.trim()) : [],
        answer: (answer ?? "").trim(),
        analysis: v.analysis ?? "",
      };
      if (question?.id) return unwrap(await api.PUT("/api/teacher/questions/{qid}", { params: { path: { qid: question.id } }, body }));
      return unwrap(await api.POST("/api/teacher/questions", { body }));
    },
    onSuccess: () => {
      message.success(question?.id ? "已保存" : "已录入题库");
      invalidate();
      onClose();
    },
    onError: (e) => message.error(e.message),
  });

  const choice = CHOICE.has(qtype ?? "");
  const letterOptions = options.map((_, i) => ({ value: LETTERS[i], label: LETTERS[i] }));

  return (
    <Modal
      title={question?.id ? "修改题目" : "手动录题"}
      open={Boolean(question)}
      onCancel={onClose}
      onOk={() => form.submit()}
      okButtonProps={{ loading: save.isPending }}
      destroyOnHidden
      width={720}
    >
      <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
        <Row gutter={12}>
          <Col xs={12} sm={6}>
            <Form.Item name="subject" label="学科">
              <Select options={SUBJECTS.map((s) => ({ value: s, label: s }))} />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item name="grade" label="年级">
              <Select allowClear options={GRADES.map((g) => ({ value: g, label: g }))} placeholder="不限" />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item name="qtype" label="题型">
              <Select options={QTYPES.map((t) => ({ value: t, label: t }))} />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item name="difficulty" label="难度">
              <Select options={DIFFICULTIES.map((d) => ({ value: d, label: d }))} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="stem"
          label="题干"
          extra={qtype === "填空题" ? "用 ＿＿＿＿ 表示要填的空；公式用 $...$" : "公式用 $...$，例如 $\\frac{1}{2}$"}
          rules={[{ required: true, whitespace: true, message: "请填写题干" }]}
        >
          <Input.TextArea rows={3} maxLength={5000} />
        </Form.Item>
        {stem.includes("$") && (
          <div className="math-preview" style={{ textAlign: "left" }}>
            <MarkdownView text={stem} />
          </div>
        )}
        {choice && (
          <Form.List name="options">
            {(fields, { add, remove }) => (
              <Form.Item label="选项">
                {fields.map((field, i) => (
                  <Space key={field.key} style={{ display: "flex", marginBottom: 8 }} align="start">
                    <Typography.Text strong style={{ lineHeight: "32px" }}>
                      {LETTERS[i]}.
                    </Typography.Text>
                    <Form.Item name={field.name} noStyle rules={[{ required: true, whitespace: true, message: "选项不能为空" }]}>
                      <Input maxLength={1000} style={{ width: 520, maxWidth: "calc(100vw - 160px)" }} />
                    </Form.Item>
                    {fields.length > 3 && <Button type="text" icon={<DeleteOutlined />} aria-label="删除选项" onClick={() => remove(field.name)} />}
                  </Space>
                ))}
                {fields.length < 6 && (
                  <Button type="dashed" size="small" onClick={() => add("")}>
                    添加选项
                  </Button>
                )}
              </Form.Item>
            )}
          </Form.List>
        )}
        {choice ? (
          qtype === "单选题" ? (
            <Form.Item name="single" label="正确选项" rules={[{ required: true, message: "请选择正确选项" }]}>
              <Radio.Group options={letterOptions} />
            </Form.Item>
          ) : (
            <Form.Item name="letters" label="正确选项" rules={[{ required: true, message: "请选择正确选项" }]}>
              <Checkbox.Group options={letterOptions} />
            </Form.Item>
          )
        ) : qtype === "判断题" ? (
          <Form.Item name="answer" label="答案" rules={[{ required: true, message: "请选择答案" }]}>
            <Radio.Group options={["对", "错"]} />
          </Form.Item>
        ) : (
          <Form.Item
            name="answer"
            label="答案"
            extra={qtype === "填空题" ? "多个空的答案用“；”隔开" : undefined}
            rules={[{ required: true, whitespace: true, message: "请填写答案" }]}
          >
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
        )}
        <Form.Item name="analysis" label="解析">
          <Input.TextArea rows={4} maxLength={5000} />
        </Form.Item>
        <Form.Item name="knowledge_points" label="知识点" extra="输入后按回车，最多 5 个">
          <Select mode="tags" maxCount={5} open={false} placeholder="例如：有理数的加法" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
