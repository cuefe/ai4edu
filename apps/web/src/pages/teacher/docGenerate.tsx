import { FolderOpenOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, App, Card, Empty, Form, Select, Space, Spin, Switch, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, unwrap } from "@/api/client";
import { postSSE } from "@/api/sse";
import { MarkdownView } from "@/components/MarkdownView";
import { DOC_TYPES, type DocType } from "./lessonPlanOptions";

type Phase = "idle" | "streaming" | "error";
type SourceItem = { n: number; resource_id: string; label: string };

/** 生成表单里的“参考资料库”开关和资料选择，教案、讲义、出题共用。 */
export function LibraryField({ subject, enabled, hint }: { subject?: string; enabled: boolean; hint: string }) {
  const resources = useQuery({
    queryKey: ["teacher", "resources"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/resources")),
  });
  // 只列出解析完成、学科匹配（或不限学科）的资料，和后端检索的范围一致
  const options = (resources.data ?? [])
    .filter((r) => r.status === "ready" && (!r.subject || r.subject === subject))
    .map((r) => ({ value: r.id, label: r.mine ? r.filename : `${r.filename}（${r.owner_name}）` }));
  return (
    <>
      <Form.Item label="参考资料库" style={{ marginBottom: 8 }}>
        <Space>
          <Form.Item name="use_library" valuePropName="checked" noStyle>
            <Switch />
          </Form.Item>
          <Typography.Text type="secondary">{hint}</Typography.Text>
        </Space>
      </Form.Item>
      {enabled && (
        <Form.Item
          name="resource_ids"
          extra={
            options.length === 0 && !resources.isLoading ? (
              <>
                资料库里还没有{subject}资料，<Link to="/teacher/resources">去上传</Link>
              </>
            ) : (
              "不选就在全部资料里检索"
            )
          }
        >
          <Select
            mode="multiple"
            allowClear
            loading={resources.isLoading}
            options={options}
            placeholder="只参考这几份资料（选填）"
            showSearch={{ optionFilterProp: "label" }}
            maxCount={20}
          />
        </Form.Item>
      )}
    </>
  );
}

/** 流式生成教案、讲义：发请求、攒文字、收到 done 后跳到编辑页。 */
export function useDocStream(docType: DocType) {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [phase, setPhase] = useState<Phase>("idle");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sources, setSources] = useState<SourceItem[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const config = DOC_TYPES[docType];

  useEffect(() => () => abortRef.current?.abort(), []);

  async function generate(values: unknown) {
    const abort = new AbortController();
    abortRef.current = abort;
    setPhase("streaming");
    setText("");
    setError("");
    setSources([]);
    // 攒一小段再刷新，避免每个字都重新渲染整篇 Markdown
    let buffer = "";
    let timer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      const chunk = buffer;
      buffer = "";
      timer = null;
      setText((t) => t + chunk);
    };
    try {
      await postSSE(
        config.generatePath,
        values,
        (event, data) => {
          const d = data as { id?: string; text?: string; message?: string; items?: SourceItem[] };
          if (event === "sources" && d.items) {
            setSources(d.items);
          } else if (event === "delta" && d.text) {
            buffer += d.text;
            timer ??= setTimeout(flush, 100);
          } else if (event === "done") {
            message.success(`${config.label}生成好了，可以直接修改`);
            navigate(`${config.base}/${d.id}`, { replace: true });
          } else if (event === "error") {
            throw new Error(d.message);
          }
        },
        abort.signal,
      );
    } catch (e) {
      if (abort.signal.aborted) return;
      setPhase("error");
      setError(e instanceof Error ? e.message : "生成失败，请稍后重试");
    } finally {
      if (timer) clearTimeout(timer);
      flush();
    }
  }

  return { phase, text, error, sources, generate, streaming: phase === "streaming", config };
}

export function PreviewCard({ stream, idleHint }: { stream: ReturnType<typeof useDocStream>; idleHint: string }) {
  const { phase, text, error, sources, streaming, config } = stream;
  const previewRef = useRef<HTMLDivElement>(null);

  // 内容在底部附近时跟着滚动；老师往上翻看时不打扰
  useEffect(() => {
    const el = previewRef.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 120) el.scrollTop = el.scrollHeight;
  }, [text]);

  return (
    <Card
      title="预览"
      extra={streaming && <Typography.Text type="secondary">大约需要 1～2 分钟，离开页面不影响生成</Typography.Text>}
      styles={{ body: { padding: 0 } }}
    >
      {phase === "error" && (
        <Alert
          type="error"
          showIcon
          title={error}
          description={`可以稍后重试；如果已经生成了一部分，能在${config.label}列表里看到。`}
          style={{ margin: 16 }}
        />
      )}
      {sources.length > 0 && (
        <div className="doc-sources">
          <FolderOpenOutlined /> 参考了资料库中的 {sources.length} 个片段：
          {sources.map((s) => (
            <Tag key={s.n} style={{ marginInlineEnd: 4 }}>
              [{s.n}] {s.label}
            </Tag>
          ))}
        </div>
      )}
      <div ref={previewRef} className="doc-preview">
        {text ? (
          <MarkdownView text={text} />
        ) : (
          <Empty
            style={{ padding: "64px 0" }}
            description={streaming ? "AI 正在构思…" : idleHint}
            image={streaming ? <Spin size="large" /> : Empty.PRESENTED_IMAGE_SIMPLE}
          />
        )}
      </div>
    </Card>
  );
}
