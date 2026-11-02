import { ArrowLeftOutlined, FileWordOutlined, ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import type { Editor } from "@tiptap/react";
import { Alert, App, Button, Card, Input, Result, Space, Spin, Typography } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ApiError, api, unwrap, type Schemas } from "@/api/client";
import { DocEditor } from "@/components/DocEditor";
import { MarkdownView } from "@/components/MarkdownView";
import { exportDocx } from "./LessonPlansPage";

type DocumentOut = Schemas["DocumentOut"];
type SaveState = "saved" | "dirty" | "saving" | "error";

const AUTOSAVE_MS = 1500;

export function LessonPlanEditPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["teacher", "document", id],
    queryFn: async () => unwrap(await api.GET("/api/teacher/documents/{doc_id}", { params: { path: { doc_id: id } } })),
    // 编辑中不能被后台刷新覆盖；只有生成中才轮询进度
    refetchOnWindowFocus: false,
    refetchInterval: (q) => (q.state.data?.status === "generating" ? 2000 : false),
  });
  const doc = query.data;

  if (query.isLoading) return <Spin style={{ display: "block", marginTop: 96 }} />;
  if (!doc) {
    return (
      <Result
        status="404"
        title={query.error?.message ?? "教案不存在"}
        extra={<Button onClick={() => navigate("/teacher/lesson-plans")}>返回教案列表</Button>}
      />
    );
  }
  if (doc.status === "generating") {
    return (
      <Card title={doc.title}>
        <Alert type="info" showIcon title="教案还在生成中，生成完会自动进入编辑" style={{ marginBottom: 16 }} />
        <MarkdownView text={doc.generated_md ?? ""} />
      </Card>
    );
  }
  if (doc.status === "failed") {
    return (
      <Result
        status="error"
        title="教案生成失败"
        subTitle={doc.error}
        extra={[
          <Button key="retry" type="primary" onClick={() => navigate(`/teacher/lesson-plans/new?from=${doc.id}`)}>
            重新生成
          </Button>,
          <Button key="back" onClick={() => navigate("/teacher/lesson-plans")}>
            返回教案列表
          </Button>,
        ]}
      />
    );
  }
  return <LessonPlanEditor key={doc.id} doc={doc} />;
}

function SaveStatus({ state, savedAt, onRetry }: { state: SaveState; savedAt: Date | null; onRetry: () => void }) {
  if (state === "saving") return <Typography.Text type="secondary">保存中…</Typography.Text>;
  if (state === "dirty") return <Typography.Text type="secondary">有未保存的修改</Typography.Text>;
  if (state === "error") {
    return (
      <Typography.Text type="danger">
        保存失败，<Typography.Link onClick={onRetry}>重试</Typography.Link>
      </Typography.Text>
    );
  }
  return <Typography.Text type="secondary">{savedAt ? `已保存 ${dayjs(savedAt).format("HH:mm:ss")}` : "已保存"}</Typography.Text>;
}

function LessonPlanEditor({ doc }: { doc: DocumentOut }) {
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const editorRef = useRef<Editor | null>(null);
  const [title, setTitle] = useState(doc.title);
  const [state, setState] = useState<SaveState>("saved");
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [exporting, setExporting] = useState(false);
  const [showWarnings, setShowWarnings] = useState(true);

  // 保存相关的状态放在 ref 里：编辑器的回调在创建时就固定了，读 state 会拿到旧值
  const titleRef = useRef(doc.title);
  const version = useRef(doc.version);
  const dirty = useRef(false);
  const conflict = useRef(false);
  const inflight = useRef<Promise<boolean> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const save = useCallback(async (): Promise<boolean> => {
    clearTimeout(timer.current);
    if (inflight.current) await inflight.current;
    const editor = editorRef.current;
    if (!dirty.current || conflict.current || !editor) return !dirty.current;
    dirty.current = false;
    setState("saving");
    const run = (async () => {
      try {
        const out = unwrap(
          await api.PUT("/api/teacher/documents/{doc_id}", {
            params: { path: { doc_id: doc.id } },
            body: { title: titleRef.current.trim() || "未命名教案", content: editor.getJSON(), version: version.current },
          }),
        );
        version.current = out.version;
        setSavedAt(new Date());
        setState(dirty.current ? "dirty" : "saved");
        return true;
      } catch (e) {
        dirty.current = true;
        setState("error");
        if (e instanceof ApiError && e.code === "version_conflict") {
          conflict.current = true;
          modal.warning({
            title: "教案已在别的窗口修改过",
            content: "为了不覆盖那边的修改，这里不再自动保存。刷新页面可以看到最新内容。",
            okText: "刷新页面",
            onOk: () => window.location.reload(),
          });
        }
        return false;
      } finally {
        inflight.current = null;
      }
    })();
    inflight.current = run;
    return run;
  }, [doc.id, modal]);

  const saveRef = useRef(save);
  saveRef.current = save;

  const markDirty = useCallback(() => {
    dirty.current = true;
    setState("dirty");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void saveRef.current(), AUTOSAVE_MS);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void saveRef.current();
      }
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirty.current) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", onBeforeUnload);
      // 切到别的页面时把没保存的改动存掉
      if (dirty.current) void saveRef.current();
    };
  }, []);

  async function exportWord() {
    setExporting(true);
    try {
      if (!(await save())) {
        message.error("保存失败，请稍后再导出");
        return;
      }
      await exportDocx(doc.id, titleRef.current.trim() || "教案");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div style={{ display: "flex", alignItems: "center", gap: 4, flex: "1 1 320px", minWidth: 0 }}>
          <Button type="text" icon={<ArrowLeftOutlined />} aria-label="返回教案列表" onClick={() => navigate("/teacher/lesson-plans")} />
          <Input
            value={title}
            variant="borderless"
            maxLength={200}
            aria-label="教案标题"
            className="doc-title-input"
            onChange={(e) => {
              setTitle(e.target.value);
              titleRef.current = e.target.value;
              markDirty();
            }}
          />
        </div>
        <Space wrap>
          <SaveStatus state={state} savedAt={savedAt} onRetry={() => void save()} />
          <Button icon={<ReloadOutlined />} onClick={() => navigate(`/teacher/lesson-plans/new?from=${doc.id}`)}>
            重新生成
          </Button>
          <Button type="primary" icon={<FileWordOutlined />} loading={exporting} onClick={exportWord}>
            导出 Word
          </Button>
        </Space>
      </div>
      {showWarnings && doc.warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          closable={{ onClose: () => setShowWarnings(false) }}
          title="AI 自检发现以下问题，请核对"
          description={
            <ul style={{ margin: 0, paddingInlineStart: 20 }}>
              {doc.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          }
          style={{ marginBottom: 16 }}
        />
      )}
      <DocEditor initialContent={doc.content ?? { type: "doc", content: [] }} onChange={markDirty} editorRef={editorRef} />
    </>
  );
}
