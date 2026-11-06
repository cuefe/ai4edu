import { ArrowLeftOutlined, CameraOutlined, CheckCircleOutlined, CloseOutlined, CreditCardOutlined, MessageOutlined, SendOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Collapse, Drawer, Empty, Result, Space, Spin, Tag, Typography, Upload } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ApiError, api, authFetch, unwrap, type Schemas } from "@/api/client";
import { AnswerInput } from "@/components/AnswerInput";
import { AuthImage } from "@/components/AuthImage";
import { MarkdownView } from "@/components/MarkdownView";
import { TutorChat } from "@/components/TutorChat";
import { StudentPage, dueTag, teacherLabel } from "./StudentHome";

type Detail = Schemas["StudentAssignment"];
type Item = Schemas["ItemOut"];
type Answer = Schemas["AnswerOut"];

const SAVE_DELAY = 800;
const ORIGIN_LABELS: Record<string, string> = { this_week: "本周内容", weak: "巩固薄弱点", wrong: "错题同类题", review: "复习" };

async function uploadPhoto(aid: string, itemId: string, file: File): Promise<Answer> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await authFetch(new Request(`/api/student/assignments/${aid}/answers/${itemId}/images`, { method: "POST", body: fd }));
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(data.message ?? "上传失败", resp.status, data.code);
  return data as Answer;
}

function ResultLine({ answer, item, revealed }: { answer?: Answer; item: Item; revealed: boolean }) {
  if (!answer || answer.status === "draft") return <Tag>没有作答</Tag>;
  if (answer.score == null) return <Tag color="orange">老师批改中</Tag>;
  return (
    <Space wrap>
      {answer.correct ? (
        <Tag color="green" icon={<CheckCircleOutlined />}>
          正确 {answer.score} 分
        </Tag>
      ) : (
        <Tag color="red" icon={<CloseOutlined />}>
          {answer.score} / {item.score} 分
        </Tag>
      )}
      {!revealed && <Typography.Text type="secondary">答案截止后公布</Typography.Text>}
    </Space>
  );
}

function QuestionCard({
  detail,
  item,
  answer,
  value,
  onChange,
  onAsk,
  onPhotos,
}: {
  detail: Detail;
  item: Item;
  answer?: Answer;
  value: string;
  onChange: (v: string) => void;
  onAsk: () => void;
  onPhotos: (a: Answer) => void;
}) {
  const { message } = App.useApp();
  const c = item.content as { qtype: string; stem: string; options?: string[]; answer?: string; analysis?: string; origin?: string };
  const editing = detail.status === "todo";
  // 周测的题说明为什么考它；交卷后才显示，免得影响作答
  const origin = !editing && c.origin ? ORIGIN_LABELS[c.origin] : undefined;
  const photos = answer?.image_count ?? 0;
  const removePhoto = useMutation({
    mutationFn: async (index: number) =>
      unwrap(
        await api.DELETE("/api/student/assignments/{aid}/answers/{item_id}/images/{index}", {
          params: { path: { aid: detail.id, item_id: item.id, index } },
        }),
      ),
    onSuccess: onPhotos,
    onError: (e) => message.error(e.message),
  });
  return (
    <Card size="small" className="q-card" style={{ marginBottom: 12 }}>
      <Space size={4} wrap style={{ marginBottom: 6 }}>
        <Typography.Text strong>{item.seq + 1}.</Typography.Text>
        <Tag>{c.qtype}</Tag>
        <Tag>{item.score} 分</Tag>
        {origin && <Tag color="purple">{origin}</Tag>}
        {!editing && <ResultLine answer={answer} item={item} revealed={detail.revealed} />}
      </Space>
      <MarkdownView text={c.stem} />
      <div style={{ margin: "8px 0" }}>
        <AnswerInput qtype={c.qtype} stem={c.stem} options={c.options ?? []} value={value} onChange={onChange} disabled={!editing} />
      </div>
      {(c.qtype === "解答题" || photos > 0) && (
        <Space wrap align="start">
          {Array.from({ length: photos }, (_, i) => (
            <span key={`${i}-${photos}`} className="pending-img-lg">
              <AuthImage src={`/api/student/assignments/${detail.id}/answers/${item.id}/images/${i}`} alt={`作答照片 ${i + 1}`} width={120} />
              {editing && (
                <Button size="small" type="text" danger icon={<CloseOutlined />} aria-label="删除照片" onClick={() => removePhoto.mutate(i)} />
              )}
            </span>
          ))}
          {editing && photos < 3 && (
            <Upload
              accept="image/*"
              showUploadList={false}
              customRequest={({ file, onSuccess, onError }) => {
                uploadPhoto(detail.id, item.id, file as File)
                  .then((a) => {
                    onPhotos(a);
                    onSuccess?.(a);
                  })
                  .catch((e: Error) => {
                    message.error(e.message);
                    onError?.(e);
                  });
              }}
            >
              <Button icon={<CameraOutlined />}>拍照上传</Button>
            </Upload>
          )}
        </Space>
      )}
      {editing && detail.allow_ai && (
        <div style={{ marginTop: 8 }}>
          <Button type="link" icon={<MessageOutlined />} onClick={onAsk} style={{ paddingInline: 0 }}>
            没思路？问问 AI（只给提示）
          </Button>
        </div>
      )}
      {!editing && answer && (answer.teacher_comment || answer.ai_comment) && (
        <Alert type="info" showIcon title={answer.teacher_comment || answer.ai_comment} style={{ marginTop: 8 }} />
      )}
      {!editing && detail.revealed && c.answer && (
        <Collapse
          size="small"
          ghost
          style={{ marginInline: -16 }}
          items={[
            {
              key: "a",
              label: "看答案和解析",
              children: (
                <>
                  <div>
                    <Typography.Text strong>答案：</Typography.Text>
                    <MarkdownView text={c.answer} inline />
                  </div>
                  {c.analysis && <MarkdownView text={c.analysis} />}
                </>
              ),
            },
          ]}
        />
      )}
    </Card>
  );
}

export function StudentAssignmentPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const key = ["student", "assignment", id];
  const detail = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await api.GET("/api/student/assignments/{aid}", { params: { path: { aid: id } } })),
    refetchOnWindowFocus: false,
    refetchInterval: (q) => (q.state.data?.status === "submitted" ? 5000 : false),
  });
  const [values, setValues] = useState<Record<string, string>>({});
  const [askSession, setAskSession] = useState<string | null>(null);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const pending = useRef<Record<string, string>>({});

  useEffect(() => {
    if (detail.data) setValues((v) => ({ ...Object.fromEntries(detail.data.answers.map((a) => [a.item_id, a.response])), ...v }));
  }, [detail.data]);

  const save = async (itemId: string) => {
    clearTimeout(timers.current[itemId]);
    const response = pending.current[itemId];
    if (response === undefined) return;
    delete pending.current[itemId];
    await api.PUT("/api/student/assignments/{aid}/answers/{item_id}", { params: { path: { aid: id, item_id: itemId } }, body: { response } });
  };
  const flushAll = () => Promise.all(Object.keys(pending.current).map(save));
  const flushRef = useRef(flushAll);
  flushRef.current = flushAll;
  useEffect(() => () => void flushRef.current(), []); // 离开页面时把没保存的作答存掉

  const change = (itemId: string, v: string) => {
    setValues((all) => ({ ...all, [itemId]: v }));
    pending.current[itemId] = v;
    clearTimeout(timers.current[itemId]);
    timers.current[itemId] = setTimeout(() => void save(itemId), SAVE_DELAY);
  };

  const submit = useMutation({
    mutationFn: async () => {
      await flushAll();
      return unwrap(await api.POST("/api/student/assignments/{aid}/submit", { params: { path: { aid: id } } }));
    },
    onSuccess: (d) => {
      qc.setQueryData(key, d);
      qc.invalidateQueries({ queryKey: ["student", "assignments"] });
      qc.invalidateQueries({ queryKey: ["student", "wrong"] });
      message.success(d.pending_count ? "提交成功，解答题等老师批改" : "提交成功");
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    onError: (e) => message.error(e.message),
  });
  const done = useMutation({
    mutationFn: async (itemId: string) =>
      unwrap(await api.POST("/api/student/assignments/{aid}/items/{item_id}/done", { params: { path: { aid: id, item_id: itemId } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });
  const ask = useMutation({
    mutationFn: async (itemId: string) =>
      unwrap(await api.POST("/api/student/tutor/sessions", { body: { mode: "homework", assignment_id: id, item_id: itemId } })),
    onSuccess: (s) => setAskSession(s.id),
    onError: (e) => message.error(e.message),
  });

  if (detail.isLoading) return <Spin style={{ display: "block", marginTop: 96 }} />;
  const d = detail.data;
  if (!d) return <Result status="404" title={detail.error?.message ?? "作业不存在"} extra={<Button onClick={() => navigate("/student")}>回到首页</Button>} />;
  const answers = new Map(d.answers.map((a) => [a.item_id, a]));
  const questions = d.items.filter((i) => i.item_type === "question");

  const confirmSubmit = () => {
    const empty = questions.filter((q) => !(values[q.id] ?? "").trim() && !answers.get(q.id)?.image_count).length;
    modal.confirm({
      title: d.kind === "weekly" ? "交卷？" : "提交作业？",
      content: empty ? `还有 ${empty} 道题没有作答，提交后不能再修改。` : "提交后不能再修改。",
      okText: "提交",
      onOk: () => submit.mutateAsync(),
    });
  };

  return (
    <StudentPage>
      <div className="page-head">
        <Space align="start">
          <Button type="text" icon={<ArrowLeftOutlined />} aria-label="返回" onClick={() => navigate(-1)} />
          <div>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {d.title}
            </Typography.Title>
            <Space wrap>
              {d.kind === "weekly" && <Tag color="purple">周测</Tag>}
              <Typography.Text type="secondary">
                {d.subject} · {teacherLabel(d.teacher_name)}
              </Typography.Text>
              {dueTag(d)}
            </Space>
          </div>
        </Space>
        {d.status !== "todo" && d.score != null && (
          <Typography.Title level={3} style={{ margin: 0, color: "#2f6fed" }}>
            {d.score} <Typography.Text type="secondary">/ {d.total_score} 分</Typography.Text>
          </Typography.Title>
        )}
      </div>
      {d.note && <Alert type="info" showIcon title={d.kind === "weekly" ? d.note : `老师说：${d.note}`} style={{ marginBottom: 16 }} />}
      {d.status === "submitted" && <Alert type="warning" showIcon title={`有 ${d.pending_count} 道题老师还在批改，批改完会显示总分`} style={{ marginBottom: 16 }} />}
      {d.items.length === 0 && <Empty />}
      {d.items.map((item) => {
        if (item.item_type === "document") {
          const c = item.content as { title: string; markdown: string };
          const read = Boolean(d.progress[item.id]);
          return (
            <Card key={item.id} size="small" style={{ marginBottom: 12 }} title={<Space><Tag color="green">阅读</Tag>{c.title}</Space>}>
              <Collapse ghost size="small" style={{ marginInline: -16 }} items={[{ key: "doc", label: "展开阅读", children: <MarkdownView text={c.markdown} /> }]} />
              <Button size="small" icon={<CheckCircleOutlined />} disabled={read} loading={done.isPending} onClick={() => done.mutate(item.id)}>
                {read ? "已读完" : "我读完了"}
              </Button>
            </Card>
          );
        }
        if (item.item_type === "recite") {
          const c = item.content as { title: string; cards: unknown[] };
          const learned = d.recite_progress[item.id] ?? 0;
          return (
            <Card key={item.id} size="small" style={{ marginBottom: 12 }} title={<Space><Tag color="purple">背诵</Tag>{c.title}</Space>}>
              <Space wrap>
                <Typography.Text>
                  共 {c.cards.length} 张卡片，已学 {learned} 张
                </Typography.Text>
                <Button type="primary" icon={<CreditCardOutlined />} onClick={() => navigate(`/student/review?item=${item.id}`)}>
                  {learned >= c.cards.length ? "再复习一遍" : "去背诵"}
                </Button>
              </Space>
            </Card>
          );
        }
        return (
          <QuestionCard
            key={item.id}
            detail={d}
            item={item}
            answer={answers.get(item.id)}
            value={values[item.id] ?? ""}
            onChange={(v) => change(item.id, v)}
            onAsk={() => ask.mutate(item.id)}
            onPhotos={() => qc.invalidateQueries({ queryKey: key })}
          />
        );
      })}
      {d.status === "todo" && questions.length > 0 && (
        <Button type="primary" size="large" block icon={<SendOutlined />} loading={submit.isPending} onClick={confirmSubmit}>
          {d.kind === "weekly" ? "交卷" : "提交作业"}
        </Button>
      )}
      <Drawer title="问 AI" open={Boolean(askSession)} onClose={() => setAskSession(null)} size="large" destroyOnHidden>
        {askSession && <TutorChat sessionId={askSession} />}
      </Drawer>
    </StudentPage>
  );
}
