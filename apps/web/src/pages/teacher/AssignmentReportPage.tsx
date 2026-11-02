import { BellOutlined, CheckOutlined, DeleteOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  Drawer,
  Empty,
  Image,
  Input,
  InputNumber,
  Popconfirm,
  Progress,
  Result,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { AuthImage } from "@/components/AuthImage";
import { MarkdownView } from "@/components/MarkdownView";

type Report = Schemas["AssignmentReport"];
type Grading = Schemas["GradingRow"];
type Answer = Schemas["AnswerOut"];
type Item = Schemas["ItemOut"];

const SUB_STATUS: Record<string, { color: string; label: string }> = {
  todo: { color: "default", label: "未提交" },
  submitted: { color: "orange", label: "待批改" },
  graded: { color: "green", label: "已批改" },
};

export function QuestionBlock({ content, score, index }: { content: Record<string, unknown>; score?: number; index: number }) {
  const options = (content.options as string[] | undefined) ?? [];
  return (
    <div>
      <Space size={4} wrap>
        <Typography.Text strong>{index + 1}.</Typography.Text>
        <Tag>{String(content.qtype)}</Tag>
        {score !== undefined && <Tag>{score} 分</Tag>}
      </Space>
      <MarkdownView text={String(content.stem ?? "")} />
      {options.map((o, i) => (
        <div key={i}>
          {"ABCDEF"[i]}. <MarkdownView text={o} inline />
        </div>
      ))}
      <div className="q-answer">
        <Typography.Text type="secondary">参考答案：</Typography.Text>
        <MarkdownView text={String(content.answer ?? "")} inline />
      </div>
    </div>
  );
}

function StudentAnswer({ answer }: { answer: Answer }) {
  return (
    <>
      {answer.response ? <div className="chunk-text">{answer.response}</div> : !answer.image_count && <Typography.Text type="secondary">（没有作答）</Typography.Text>}
      {answer.image_count > 0 && (
        <Image.PreviewGroup>
          <Space wrap style={{ marginTop: 8 }}>
            {Array.from({ length: answer.image_count }, (_, i) => (
              <AuthImage key={i} src={`/api/teacher/answers/${answer.id}/images/${i}`} alt={`作答照片 ${i + 1}`} />
            ))}
          </Space>
        </Image.PreviewGroup>
      )}
    </>
  );
}

function GradingCard({ row, onDone }: { row: Grading; onDone: () => void }) {
  const { message } = App.useApp();
  const [score, setScore] = useState<number | null>(row.ai_score);
  const [comment, setComment] = useState("");
  const confirm = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/teacher/answers/{answer_id}/confirm", {
          params: { path: { answer_id: row.id } },
          body: { score, comment: comment || null },
        }),
      ),
    onSuccess: () => {
      message.success("已确认");
      onDone();
    },
    onError: (e) => message.error(e.message),
  });
  const grading = row.status === "grading";
  const low = row.ai_confidence != null && row.ai_confidence < 0.7;
  return (
    <Card size="small" style={{ marginBottom: 12 }} className={low ? "q-card q-disputed" : "q-card"}>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Typography.Text strong>{row.student_name}</Typography.Text>
          <Collapse ghost size="small" style={{ marginInline: -16 }} items={[{ key: "q", label: `第 ${row.item_seq + 1} 题（${row.item_score} 分）`, children: <QuestionBlock content={row.question} index={row.item_seq} /> }]} />
          <Typography.Text type="secondary">学生作答：</Typography.Text>
          <StudentAnswer answer={row} />
        </Col>
        <Col xs={24} md={12}>
          {grading ? (
            <Alert type="info" showIcon title="AI 正在批改…" />
          ) : (
            <>
              <Space wrap>
                <Typography.Text>AI 给分：</Typography.Text>
                <Typography.Text strong>{row.ai_score ?? "—"}</Typography.Text>
                {row.ai_confidence != null && <Tag color={low ? "orange" : "green"}>把握 {Math.round(row.ai_confidence * 100)}%</Tag>}
              </Space>
              {row.ai_points.length > 0 && (
                <ul style={{ margin: "4px 0", paddingInlineStart: 18 }}>
                  {row.ai_points.map((p) => (
                    <li key={p}>
                      <Typography.Text type="danger">{p}</Typography.Text>
                    </li>
                  ))}
                </ul>
              )}
              {row.ai_comment && <Typography.Paragraph type="secondary">评语：{row.ai_comment}</Typography.Paragraph>}
              <Space wrap>
                <InputNumber min={0} max={row.item_score} step={0.5} value={score} onChange={setScore} suffix="分" style={{ width: 100 }} />
                <Input placeholder="补充评语（选填）" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} style={{ width: 200 }} />
                <Button type="primary" icon={<CheckOutlined />} loading={confirm.isPending} disabled={score == null} onClick={() => confirm.mutate()}>
                  {score === row.ai_score ? "确认" : "改分并确认"}
                </Button>
              </Space>
            </>
          )}
        </Col>
      </Row>
    </Card>
  );
}

function SubmissionDrawer({ report, subId, onClose }: { report: Report; subId: string | null; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ["teacher", "submission", subId],
    enabled: Boolean(subId),
    queryFn: async () =>
      unwrap(await api.GET("/api/teacher/assignments/{aid}/submissions/{sid}", { params: { path: { aid: report.id, sid: subId! } } })),
  });
  const answers = new Map((detail.data?.answers ?? []).map((a) => [a.item_id, a]));
  const s = detail.data?.submission;
  return (
    <Drawer title={s ? `${s.student_name} 的作答` : ""} open={Boolean(subId)} onClose={onClose} size="large">
      <Spin spinning={detail.isLoading}>
        {s && (
          <Typography.Paragraph>
            <Tag color={SUB_STATUS[s.status].color}>{SUB_STATUS[s.status].label}</Tag>
            {s.score != null && `得分 ${s.score} / ${report.total_score}`}
            {s.late && <Tag color="red" style={{ marginInlineStart: 8 }}>迟交</Tag>}
          </Typography.Paragraph>
        )}
        {report.items
          .filter((i) => i.item_type === "question")
          .map((item) => {
            const a = answers.get(item.id);
            return (
              <Card key={item.id} size="small" style={{ marginBottom: 12 }}>
                <QuestionBlock content={item.content} score={item.score} index={item.seq} />
                {a ? (
                  <>
                    <Space style={{ margin: "8px 0" }}>
                      {a.score != null ? <Tag color={a.correct ? "green" : "red"}>{a.score} 分</Tag> : <Tag color="orange">待确认</Tag>}
                    </Space>
                    <StudentAnswer answer={a} />
                    {(a.ai_comment || a.teacher_comment) && (
                      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                        {a.teacher_comment || a.ai_comment}
                      </Typography.Paragraph>
                    )}
                  </>
                ) : (
                  <Typography.Text type="secondary">没有作答</Typography.Text>
                )}
              </Card>
            );
          })}
      </Spin>
    </Drawer>
  );
}

function ItemAnalysis({ report }: { report: Report }) {
  const stats = new Map(report.item_stats.map((s) => [s.item_id, s]));
  const questions = report.items.filter((i: Item) => i.item_type === "question");
  const common = report.item_stats.filter((s) => s.common_wrong).length;
  return (
    <>
      {common > 0 && <Alert type="warning" showIcon title={`有 ${common} 道共性错题（错误率 40% 以上），建议课上重点讲`} style={{ marginBottom: 12 }} />}
      {questions.length === 0 && <Empty description="这份作业没有题目" />}
      {questions.map((item) => {
        const s = stats.get(item.id);
        return (
          <Card key={item.id} size="small" style={{ marginBottom: 12 }} className={s?.common_wrong ? "q-card q-disputed" : "q-card"}>
            <Row gutter={16}>
              <Col xs={24} md={16}>
                <QuestionBlock content={item.content} score={item.score} index={item.seq} />
              </Col>
              <Col xs={24} md={8}>
                {s && s.answered > 0 ? (
                  <>
                    <Typography.Text type="secondary">正确率</Typography.Text>
                    <Progress percent={Math.round((s.accuracy ?? 0) * 100)} status={s.common_wrong ? "exception" : "normal"} />
                    <Typography.Text type="secondary">
                      {s.correct}/{s.answered} 人得满分，平均 {s.avg_score} 分
                    </Typography.Text>
                    {s.common_wrong && <Tag color="red" style={{ marginTop: 4 }}>共性错题</Tag>}
                  </>
                ) : (
                  <Typography.Text type="secondary">还没有出分</Typography.Text>
                )}
              </Col>
            </Row>
          </Card>
        );
      })}
    </>
  );
}

export function AssignmentReportPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [viewing, setViewing] = useState<string | null>(null);
  const report = useQuery({
    queryKey: ["teacher", "assignment", id],
    queryFn: async () => unwrap(await api.GET("/api/teacher/assignments/{aid}", { params: { path: { aid: id } } })),
  });
  const grading = useQuery({
    queryKey: ["teacher", "assignment", id, "grading"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/assignments/{aid}/grading", { params: { path: { aid: id } } })),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "grading") ? 3000 : false),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["teacher", "assignment", id] });
    qc.invalidateQueries({ queryKey: ["teacher", "assignments"] });
  };
  const remind = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/teacher/assignments/{aid}/remind", { params: { path: { aid: id } } })),
    onSuccess: (r) => message.success(r.count ? `已提醒 ${r.count} 名学生` : "学生都提交了"),
    onError: (e) => message.error(e.message),
  });
  const confirmAll = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/teacher/assignments/{aid}/confirm-all", { params: { path: { aid: id } } })),
    onSuccess: (r) => {
      message.success(`已确认 ${r.count} 道`);
      refresh();
    },
    onError: (e) => message.error(e.message),
  });
  const remove = useMutation({
    mutationFn: async () => unwrap(await api.DELETE("/api/teacher/assignments/{aid}", { params: { path: { aid: id } } })),
    onSuccess: () => {
      message.success("已删除");
      navigate("/teacher/assignments", { replace: true });
    },
    onError: (e) => message.error(e.message),
  });

  if (report.isLoading) return <Spin style={{ display: "block", marginTop: 96 }} />;
  const r = report.data;
  if (!r) return <Result status="404" title={report.error?.message ?? "作业不存在"} extra={<Button onClick={() => navigate("/teacher/assignments")}>返回作业列表</Button>} />;
  const todo = r.student_count - r.submitted_count;
  const rows = grading.data ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {r.title}
          </Typography.Title>
          <Typography.Text type="secondary">
            {r.subject} · {r.class_names.join("、")} · {dayjs(r.publish_at).format("MM-DD HH:mm")} 发布
            {r.due_at && ` · ${dayjs(r.due_at).format("MM-DD HH:mm")} 截止`}
            {!r.allow_ai && " · 不能问 AI"}
          </Typography.Text>
        </div>
        <Space wrap>
          <Button icon={<BellOutlined />} disabled={todo === 0} loading={remind.isPending} onClick={() => remind.mutate()}>
            一键催交（{todo}）
          </Button>
          <Popconfirm title="删除这份作业？学生的作答和成绩也会删除" onConfirm={() => remove.mutate()}>
            <Button danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      </div>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="提交" value={r.submitted_count} suffix={`/ ${r.student_count}`} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="平均分" value={r.avg_score ?? "—"} suffix={r.avg_score != null ? `/ ${r.total_score}` : undefined} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="已批改完" value={r.graded_count} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="待确认批改" value={r.pending_review} styles={{ content: { color: r.pending_review ? "#fa8c16" : undefined } }} />
          </Card>
        </Col>
      </Row>
      <Tabs
        defaultActiveKey={r.pending_review ? "grading" : "items"}
        items={[
          { key: "items", label: "题目分析", children: <ItemAnalysis report={r} /> },
          {
            key: "students",
            label: "学生",
            children: (
              <Table
                rowKey="id"
                size="small"
                dataSource={r.submissions}
                pagination={false}
                scroll={{ x: 640 }}
                onRow={(s) => ({ onClick: () => s.status !== "todo" && setViewing(s.id), style: { cursor: s.status !== "todo" ? "pointer" : undefined } })}
                columns={[
                  { title: "学生", render: (_, s) => `${s.student_name}${s.username ? `（${s.username}）` : ""}` },
                  { title: "班级", dataIndex: "class_name", width: 110 },
                  {
                    title: "状态",
                    width: 130,
                    render: (_, s) => (
                      <Space size={4}>
                        <Tag color={SUB_STATUS[s.status].color}>{SUB_STATUS[s.status].label}</Tag>
                        {s.late && <Tag color="red">迟交</Tag>}
                      </Space>
                    ),
                  },
                  { title: "得分", width: 90, render: (_, s) => (s.score == null ? "—" : s.score) },
                  { title: "阅读/背诵", dataIndex: "progress_done", width: 90 },
                  { title: "提交时间", dataIndex: "submitted_at", width: 120, render: (t: string | null) => (t ? dayjs(t).format("MM-DD HH:mm") : "—") },
                ]}
              />
            ),
          },
          {
            key: "grading",
            label: (
              <Space size={6}>
                批改确认
                {rows.length > 0 && <Badge count={rows.length} color="#fa8c16" />}
              </Space>
            ),
            children: (
              <>
                {rows.length === 0 ? (
                  <Empty description="没有等待确认的批改。解答题提交后 AI 先批改，再由你确认" />
                ) : (
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Typography.Text type="secondary">AI 没把握的排在前面。确认后学生才能看到分数和评语。</Typography.Text>
                    <Popconfirm title="所有 AI 已批改的题都按 AI 给的分确认？" onConfirm={() => confirmAll.mutate()}>
                      <Button icon={<CheckOutlined />} loading={confirmAll.isPending}>
                        全部按 AI 给分确认
                      </Button>
                    </Popconfirm>
                  </Space>
                )}
                {rows.map((row) => (
                  <GradingCard key={row.id} row={row} onDone={refresh} />
                ))}
              </>
            ),
          },
        ]}
      />
      <SubmissionDrawer report={r} subId={viewing} onClose={() => setViewing(null)} />
    </>
  );
}
