import { CameraOutlined, CloseCircleFilled, PhoneOutlined, SendOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Collapse, Input, Space, Spin, Tag, Typography, Upload } from "antd";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, authFetch, unwrap, type Schemas } from "@/api/client";
import { postSSE } from "@/api/sse";
import { MarkdownView } from "./MarkdownView";

type Message = Schemas["MessageOut"];
type Local = { key: string; role: string; content: string; flag?: string | null; images?: string[]; pending?: boolean };

const MODE_LABEL: Record<string, string> = { learn: "学习模式", homework: "作业提示模式", correction: "订正模式" };
const MODE_HINT: Record<string, string> = {
  learn: "可以问任何学习上的问题，也可以拍照提问。",
  homework: "作业期间 AI 只给思路和提示，不直接告诉你答案。",
  correction: "AI 会一步一步带你分析这道错题。",
};
const STYLES = [
  { key: "simpler", label: "讲简单点" },
  { key: "example", label: "举个例子" },
  { key: "mnemonic", label: "编个口诀" },
] as const;

async function uploadImage(file: File): Promise<string> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await authFetch(new Request("/api/student/tutor/images", { method: "POST", body: fd }));
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(data.message ?? "上传失败", resp.status, data.code);
  return data.key as string;
}

function toLocal(m: Message): Local {
  return { key: m.id, role: m.role, content: m.content, flag: m.flag };
}

/** 问一问对话框：显示历史消息，流式接收回复；危机回复醒目显示求助电话。 */
export function TutorChat({ sessionId }: { sessionId: string }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["student", "tutor", sessionId],
    queryFn: async () =>
      unwrap(await api.GET("/api/student/tutor/sessions/{sid}", { params: { path: { sid: sessionId } } })),
    refetchOnWindowFocus: false,
  });
  const [messages, setMessages] = useState<Local[]>([]);
  const [text, setText] = useState("");
  const [images, setImages] = useState<{ key: string; url: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [crisis, setCrisis] = useState<string[] | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (detail.data) {
      setMessages(detail.data.messages.map(toLocal));
      if (detail.data.messages.some((m) => m.flag === "crisis")) setCrisis(detail.data.hotlines);
    }
  }, [detail.data]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function send(content: string, style?: string) {
    if (busy || (!content.trim() && !images.length && !style)) return;
    const sent = images;
    setBusy(true);
    setText("");
    setImages([]);
    const replyKey = `r-${Date.now()}`;
    setMessages((m) => [
      ...m,
      { key: `u-${Date.now()}`, role: "user", content: content.trim() || (style ? STYLES.find((s) => s.key === style)?.label ?? "" : ""), images: sent.map((i) => i.url) },
      { key: replyKey, role: "assistant", content: "", pending: true },
    ]);
    const update = (fn: (r: Local) => Local) => setMessages((m) => m.map((x) => (x.key === replyKey ? fn(x) : x)));
    try {
      await postSSE(
        `/api/student/tutor/sessions/${sessionId}/messages`,
        { text: content, style: style ?? null, images: sent.map((i) => i.key) },
        (event, data) => {
          const d = data as { text?: string; message?: string; flag?: string; hotlines?: string[]; kind?: string };
          if (event === "notice" && d.kind === "crisis") setCrisis(d.hotlines ?? []);
          else if (event === "delta" && d.text) update((r) => ({ ...r, content: r.content + d.text }));
          else if (event === "done") update((r) => ({ ...r, pending: false, flag: d.flag }));
          else if (event === "error") throw new Error(d.message);
        },
      );
    } catch (e) {
      update((r) => ({ ...r, pending: false, content: r.content || "（发送失败）" }));
      message.error(e instanceof Error ? e.message : "发送失败");
    } finally {
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["student", "tutor", "sessions"] });
    }
  }

  if (detail.isLoading) return <Spin style={{ display: "block", margin: "48px auto" }} />;
  const s = detail.data;
  if (!s) return <Alert type="error" showIcon title={detail.error?.message ?? "会话不存在"} />;
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");

  return (
    <div className="tutor-chat">
      <div className="tutor-head">
        <Space wrap size={4}>
          <Tag color={s.mode === "homework" ? "orange" : s.mode === "correction" ? "purple" : "blue"}>{MODE_LABEL[s.mode]}</Tag>
          <Typography.Text type="secondary">{MODE_HINT[s.mode]}</Typography.Text>
        </Space>
        {s.question && (
          <Collapse
            size="small"
            ghost
            style={{ marginInline: -16 }}
            items={[
              {
                key: "q",
                label: "正在问的题目",
                children: (
                  <>
                    <MarkdownView text={String(s.question.stem ?? "")} />
                    {((s.question.options as string[] | undefined) ?? []).map((o, i) => (
                      <div key={i}>
                        {"ABCDEF"[i]}. <MarkdownView text={o} inline />
                      </div>
                    ))}
                  </>
                ),
              },
            ]}
          />
        )}
      </div>
      {crisis && (
        <Alert
          type="warning"
          showIcon
          icon={<PhoneOutlined />}
          title="你不是一个人，需要的时候请找人聊聊"
          description={
            <ul style={{ margin: 0, paddingInlineStart: 18 }}>
              {crisis.map((h) => (
                <li key={h}>
                  <Typography.Text strong>{h}</Typography.Text>
                </li>
              ))}
            </ul>
          }
          style={{ margin: "8px 0" }}
        />
      )}
      <div ref={listRef} className="tutor-messages">
        {messages.length === 0 && (
          <Typography.Paragraph type="secondary" style={{ textAlign: "center", marginTop: 32 }}>
            有什么不懂的，直接问我吧。可以打字，也可以拍一张题目的照片。
          </Typography.Paragraph>
        )}
        {messages.map((m) => (
          <div key={m.key} className={m.role === "user" ? "bubble bubble-user" : "bubble bubble-ai"}>
            {m.images?.map((url) => <img key={url} src={url} alt="题目照片" className="bubble-img" />)}
            {m.role === "assistant" ? (
              m.content ? <MarkdownView text={m.content} /> : <Spin size="small" />
            ) : (
              <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
            )}
          </div>
        ))}
      </div>
      {lastAssistant && !lastAssistant.pending && !lastAssistant.flag?.match(/crisis|chat|unsafe/) && (
        <Space wrap size={6} style={{ margin: "8px 0" }}>
          {STYLES.map((st) => (
            <Button key={st.key} size="small" shape="round" disabled={busy} onClick={() => send("", st.key)}>
              {st.label}
            </Button>
          ))}
        </Space>
      )}
      {images.length > 0 && (
        <Space wrap style={{ marginBottom: 8 }}>
          {images.map((img) => (
            <span key={img.key} className="pending-img">
              <img src={img.url} alt="待发送的照片" />
              <CloseCircleFilled onClick={() => setImages((list) => list.filter((x) => x.key !== img.key))} />
            </span>
          ))}
        </Space>
      )}
      <div className="tutor-input">
        <Upload
          accept="image/*"
          showUploadList={false}
          disabled={busy || images.length >= 3}
          customRequest={({ file, onSuccess, onError }) => {
            uploadImage(file as File)
              .then((key) => {
                setImages((list) => [...list, { key, url: URL.createObjectURL(file as File) }]);
                onSuccess?.(key);
              })
              .catch((e: Error) => {
                message.error(e.message);
                onError?.(e);
              });
          }}
        >
          <Button icon={<CameraOutlined />} aria-label="拍照提问" disabled={busy || images.length >= 3} />
        </Upload>
        <Input.TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoSize={{ minRows: 1, maxRows: 4 }}
          maxLength={2000}
          placeholder="输入你的问题"
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              void send(text);
            }
          }}
        />
        <Button type="primary" icon={<SendOutlined />} loading={busy} onClick={() => send(text)} aria-label="发送" />
      </div>
    </div>
  );
}
