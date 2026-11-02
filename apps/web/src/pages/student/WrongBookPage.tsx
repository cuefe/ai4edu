import { BulbOutlined, CheckCircleOutlined, DeleteOutlined, EditOutlined, MessageOutlined, RightOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Drawer, Empty, Popconfirm, Result, Segmented, Select, Space, Spin, Steps, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { AnswerInput } from "@/components/AnswerInput";
import { MarkdownView } from "@/components/MarkdownView";
import { PageHead } from "@/components/PageHead";
import { TutorChat } from "@/components/TutorChat";
import { StudentPage } from "./StudentHome";

type Wrong = Schemas["WrongItemOut"];
type Question = { qtype: string; stem: string; options?: string[]; answer: string; analysis?: string; knowledge_points?: string[] };

export function WrongBookPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<string>("pending");
  const [subject, setSubject] = useState<string>();
  const [point, setPoint] = useState<string>();
  const book = useQuery({
    queryKey: ["student", "wrong", status, subject, point],
    queryFn: async () =>
      unwrap(await api.GET("/api/student/wrong-items", { params: { query: { status, subject, knowledge_point: point } } })),
  });
  return (
    <StudentPage>
      <PageHead title="错题本" />
      <Space wrap style={{ marginBottom: 16 }}>
        <Segmented
          value={status}
          onChange={(v) => setStatus(String(v))}
          options={[
            { value: "pending", label: `待订正 ${book.data?.pending ?? ""}` },
            { value: "corrected", label: `已订正 ${book.data?.corrected ?? ""}` },
          ]}
        />
        <Select allowClear placeholder="学科" style={{ width: 110 }} options={["数学", "英语"].map((s) => ({ value: s, label: s }))} onChange={setSubject} />
        <Select
          allowClear
          showSearch
          placeholder="知识点"
          style={{ width: 180 }}
          options={(book.data?.knowledge_points ?? []).map((k) => ({ value: k, label: k }))}
          onChange={setPoint}
        />
      </Space>
      <Spin spinning={book.isLoading}>
        {book.data?.items.length === 0 && (
          <Empty description={status === "pending" ? "没有待订正的错题，真棒" : "还没有订正过的题"} />
        )}
        {book.data?.items.map((w) => {
          const q = w.question as Question;
          return (
            <Card key={w.id} size="small" hoverable style={{ marginBottom: 12 }} onClick={() => navigate(`/student/wrong/${w.id}`)}>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Space size={4} wrap>
                    <Tag>{w.subject}</Tag>
                    <Tag>{q.qtype}</Tag>
                    {(q.knowledge_points ?? []).map((k) => (
                      <Tag key={k} color="geekblue">
                        {k}
                      </Tag>
                    ))}
                    {w.wrong_count > 1 && <Tag color="red">错了 {w.wrong_count} 次</Tag>}
                  </Space>
                  <MarkdownView text={q.stem} />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {w.assignment_title} · {dayjs(w.created_at).format("MM-DD")}
                  </Typography.Text>
                </div>
                <RightOutlined />
              </div>
            </Card>
          );
        })}
      </Spin>
    </StudentPage>
  );
}

function Guide({ wid }: { wid: string }) {
  const { message } = App.useApp();
  const [step, setStep] = useState(0);
  const guide = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/student/wrong-items/{wid}/guide", { params: { path: { wid } } })),
    onError: (e) => message.error(e.message),
  });
  if (!guide.data) {
    return (
      <Button icon={<BulbOutlined />} loading={guide.isPending} onClick={() => guide.mutate()}>
        没思路？一步一步看提示
      </Button>
    );
  }
  const g = guide.data;
  const parts = [
    { title: "题目解析", body: g.analysis },
    { title: "考点分析", body: g.knowledge },
    { title: "逐步讲解", body: g.steps.map((s, i) => `${i + 1}. ${s}`).join("\n\n") },
    { title: "思路总结", body: g.summary },
  ];
  return (
    <Card size="small" title="订正提示" style={{ marginTop: 12 }}>
      <Steps size="small" current={step} items={parts.map((p) => ({ title: p.title }))} style={{ marginBottom: 12 }} />
      {parts.slice(0, step + 1).map((p) => (
        <div key={p.title} style={{ marginBottom: 12 }}>
          <Typography.Text strong>{p.title}</Typography.Text>
          <MarkdownView text={p.body} />
        </div>
      ))}
      {step < parts.length - 1 ? (
        <Space wrap>
          <Button onClick={() => setStep((s) => s + 1)}>看下一步：{parts[step + 1].title}</Button>
          <Typography.Text type="secondary">有思路了就停下来自己做</Typography.Text>
        </Space>
      ) : (
        <Typography.Text type="success">看完了，自己再做一遍吧</Typography.Text>
      )}
    </Card>
  );
}

export function WrongItemPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [response, setResponse] = useState("");
  const [result, setResult] = useState<boolean | null | undefined>(undefined);
  const [askSession, setAskSession] = useState<string | null>(null);
  const item = useQuery({
    queryKey: ["student", "wrong-item", id],
    queryFn: async () => unwrap(await api.GET("/api/student/wrong-items/{wid}", { params: { path: { wid: id } } })),
  });
  const refresh = (w: Wrong) => {
    qc.setQueryData(["student", "wrong-item", id], w);
    qc.invalidateQueries({ queryKey: ["student", "wrong"] });
  };
  const redo = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/student/wrong-items/{wid}/redo", { params: { path: { wid: id } }, body: { response } })),
    onSuccess: (r) => {
      setResult(r.correct);
      refresh(r.item);
      if (r.correct) message.success("做对了，这道题订正好了");
    },
    onError: (e) => message.error(e.message),
  });
  const selfCheck = useMutation({
    mutationFn: async (correct: boolean) =>
      unwrap(await api.POST("/api/student/wrong-items/{wid}/self-check", { params: { path: { wid: id } }, body: { correct } })),
    onSuccess: (w, correct) => {
      refresh(w);
      setResult(correct);
    },
  });
  const remove = useMutation({
    mutationFn: async () => unwrap(await api.DELETE("/api/student/wrong-items/{wid}", { params: { path: { wid: id } } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["student", "wrong"] });
      navigate("/student/wrong", { replace: true });
    },
  });
  const ask = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/student/tutor/sessions", { body: { mode: "correction", wrong_item_id: id } })),
    onSuccess: (s) => setAskSession(s.id),
    onError: (e) => message.error(e.message),
  });

  if (item.isLoading) return <Spin style={{ display: "block", marginTop: 96 }} />;
  const w = item.data;
  if (!w) return <Result status="404" title="错题不存在" extra={<Button onClick={() => navigate("/student/wrong")}>返回错题本</Button>} />;
  const q = w.question as Question;
  const corrected = w.status === "corrected";

  return (
    <StudentPage>
      <PageHead
        title="订正错题"
        extra={
          <Popconfirm title="从错题本里移除这道题？" onConfirm={() => remove.mutate()}>
            <Button type="text" danger icon={<DeleteOutlined />}>
              移除
            </Button>
          </Popconfirm>
        }
      />
      <Card>
        <Space size={4} wrap style={{ marginBottom: 8 }}>
          <Tag>{q.qtype}</Tag>
          {corrected ? <Tag color="green">已订正</Tag> : <Tag color="red">待订正</Tag>}
          <Typography.Text type="secondary">{w.assignment_title}</Typography.Text>
        </Space>
        <MarkdownView text={q.stem} />
        {(q.options ?? []).map((o, i) => (
          <div key={i}>
            {"ABCDEF"[i]}. <MarkdownView text={o} inline />
          </div>
        ))}
        <Alert type="error" title={`你当时的答案：${w.wrong_response || "（没有作答）"}`} style={{ margin: "12px 0" }} />

        <Typography.Text strong>
          <EditOutlined /> 再做一遍
        </Typography.Text>
        <div style={{ margin: "8px 0" }}>
          <AnswerInput qtype={q.qtype} stem={q.stem} options={q.options ?? []} value={response} onChange={setResponse} />
        </div>
        <Space wrap>
          <Button type="primary" loading={redo.isPending} disabled={!response.trim()} onClick={() => redo.mutate()}>
            提交订正
          </Button>
          <Button icon={<MessageOutlined />} loading={ask.isPending} onClick={() => ask.mutate()}>
            问 AI 老师
          </Button>
        </Space>
        {result === true && <Alert type="success" showIcon icon={<CheckCircleOutlined />} title="做对了！这道题订正好了" style={{ marginTop: 12 }} />}
        {result === false && <Alert type="warning" showIcon title="还不对，看看下面的提示再试试" style={{ marginTop: 12 }} />}
        {(result === null || corrected || result === false) && (
          <Card size="small" style={{ marginTop: 12 }} title="参考答案">
            <MarkdownView text={q.answer} />
            {q.analysis && <MarkdownView text={q.analysis} />}
            {result === null && (
              <Space wrap style={{ marginTop: 8 }}>
                <Typography.Text>对照答案，你这次做对了吗？</Typography.Text>
                <Button type="primary" onClick={() => selfCheck.mutate(true)}>
                  做对了
                </Button>
                <Button onClick={() => selfCheck.mutate(false)}>还没对</Button>
              </Space>
            )}
          </Card>
        )}
        {!corrected && <div style={{ marginTop: 12 }}><Guide wid={w.id} /></div>}
      </Card>
      <Drawer title="问 AI 老师" open={Boolean(askSession)} onClose={() => setAskSession(null)} size="large" destroyOnHidden>
        {askSession && <TutorChat sessionId={askSession} />}
      </Drawer>
    </StudentPage>
  );
}
