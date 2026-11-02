import { CloudUploadOutlined, DeleteOutlined, DownloadOutlined, InboxOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { ApiError, api, authFetch, downloadFile, unwrap, type Schemas } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { SUBJECTS } from "./lessonPlanOptions";

type Resource = Schemas["ResourceOut"];
type SearchHit = Schemas["SearchHit"];

const ACCEPT = ".pdf,.docx,.pptx,.jpg,.jpeg,.png,.txt,.md";
const SUBJECT_OPTIONS = [...SUBJECTS.map((s) => ({ value: s, label: s })), { value: "", label: "不限学科" }];
const QUERY_KEY = ["teacher", "resources"];

function pages(r: { page_start?: number | null; page_end?: number | null }) {
  if (r.page_start == null) return "";
  return r.page_end != null && r.page_end !== r.page_start ? `第 ${r.page_start}～${r.page_end} 页` : `第 ${r.page_start} 页`;
}

function formatSize(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function StatusCell({ r }: { r: Resource }) {
  if (r.status === "pending") return <Tag>排队中</Tag>;
  if (r.status === "parsing") {
    return (
      <Tooltip title={r.progress < 90 ? "正在提取和识别文字" : "正在建立检索索引"}>
        <Progress percent={r.progress} size="small" style={{ width: 96, margin: 0 }} />
      </Tooltip>
    );
  }
  if (r.status === "failed") {
    return (
      <Tooltip title={r.error}>
        <Tag color="error">解析失败</Tag>
      </Tooltip>
    );
  }
  return (
    <Tooltip title={r.error}>
      <Tag color={r.error ? "warning" : "success"}>{r.error ? "部分可用" : "可用"}</Tag>
    </Tooltip>
  );
}

async function uploadFile(file: File, subject: string, shared: boolean): Promise<Resource> {
  const fd = new FormData();
  fd.append("file", file);
  if (subject) fd.append("subject", subject);
  fd.append("shared", String(shared));
  const resp = await authFetch(new Request("/api/teacher/resources", { method: "POST", body: fd }));
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(data.message ?? "上传失败", resp.status, data.code);
  return data as Resource;
}

function UploadModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [subject, setSubject] = useState<string>("数学");
  const [shared, setShared] = useState(false);
  return (
    <Modal title="上传资料" open={open} onCancel={onClose} footer={null} destroyOnHidden width={560}>
      <Form layout="vertical">
        <Form.Item label="学科" extra="生成教案时只参考同学科（和不限学科）的资料">
          <Select value={subject} options={SUBJECT_OPTIONS} onChange={setSubject} style={{ width: 160 }} />
        </Form.Item>
        <Form.Item>
          <Checkbox checked={shared} onChange={(e) => setShared(e.target.checked)}>
            共享给本机构的老师（他们可以查看和检索，不能修改）
          </Checkbox>
        </Form.Item>
      </Form>
      <Upload.Dragger
        multiple
        accept={ACCEPT}
        customRequest={({ file, onSuccess, onError }) => {
          uploadFile(file as File, subject, shared)
            .then((r) => {
              onSuccess?.(r);
              qc.invalidateQueries({ queryKey: QUERY_KEY });
            })
            .catch((e: Error) => onError?.(e));
        }}
        itemRender={(node, file) => (
          <Tooltip title={file.status === "error" ? (file.error as Error | undefined)?.message : undefined}>{node}</Tooltip>
        )}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">点击或拖拽文件到这里，可以一次选多个</p>
        <p className="ant-upload-hint">支持 PDF、Word（.docx）、PPT（.pptx）、图片、文本，单个文件不超过 50MB</p>
      </Upload.Dragger>
      <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
        上传后自动解析：扫描件和图片会识别文字，几十页的扫描件需要几分钟，可以先关掉窗口。老版本的 .doc、.ppt 请先另存为 .docx、.pptx。
      </Typography.Paragraph>
    </Modal>
  );
}

function ResourceDrawer({ resource, onClose }: { resource: Resource | null; onClose: () => void }) {
  const id = resource?.id ?? "";
  const chunks = useQuery({
    queryKey: [...QUERY_KEY, id, "chunks"],
    enabled: resource?.status === "ready",
    queryFn: async () => unwrap(await api.GET("/api/teacher/resources/{rid}/chunks", { params: { path: { rid: id } } })),
  });
  return (
    <Drawer title={resource?.filename} open={Boolean(resource)} onClose={onClose} size="large">
      {resource && (
        <>
          <Typography.Paragraph type="secondary">
            {[resource.subject ?? "不限学科", resource.pages ? `${resource.pages} 页` : "", resource.ocr_pages ? `其中 ${resource.ocr_pages} 页（张）靠文字识别` : "", `${resource.chunk_count} 个片段`]
              .filter(Boolean)
              .join(" · ")}
          </Typography.Paragraph>
          {resource.error && <Alert type={resource.status === "failed" ? "error" : "warning"} showIcon title={resource.error} style={{ marginBottom: 16 }} />}
          <Typography.Paragraph type="secondary">
            下面是解析出来的内容，AI 检索时按片段查找。识别有误的地方不影响原文件，可以重新解析或修改原文件后重新上传。
          </Typography.Paragraph>
          <List
            loading={chunks.isLoading}
            dataSource={chunks.data}
            locale={{ emptyText: <Empty description="没有解析出内容" /> }}
            renderItem={(c) => (
              <List.Item style={{ display: "block" }}>
                <Space size={4} style={{ marginBottom: 4 }}>
                  <Tag>#{c.seq + 1}</Tag>
                  {pages(c) && <Tag color="blue">{pages(c)}</Tag>}
                  {c.heading && <Typography.Text type="secondary">{c.heading}</Typography.Text>}
                </Space>
                <div className="chunk-text">{c.text}</div>
              </List.Item>
            )}
          />
        </>
      )}
    </Drawer>
  );
}

function SearchBox() {
  const { message } = App.useApp();
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const search = useMutation({
    mutationFn: async (query: string) => unwrap(await api.POST("/api/teacher/resources/search", { body: { query, k: 5 } })),
    onSuccess: setHits,
    onError: (e) => message.error(e.message),
  });
  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Input.Search
        placeholder="试试检索：输入课题或知识点，看看 AI 会参考哪些内容"
        enterButton={<SearchOutlined />}
        loading={search.isPending}
        maxLength={200}
        allowClear
        onSearch={(q) => (q.trim() ? search.mutate(q.trim()) : setHits(null))}
      />
      {hits && (
        <List
          size="small"
          style={{ marginTop: 8 }}
          dataSource={hits}
          locale={{ emptyText: "没有找到相关内容" }}
          renderItem={(h) => (
            <List.Item style={{ display: "block" }}>
              <Space size={4} wrap style={{ marginBottom: 4 }}>
                <Typography.Text strong>{h.filename}</Typography.Text>
                {pages(h) && <Tag color="blue">{pages(h)}</Tag>}
                <Tag>相关度 {Math.round(h.score * 100)}%</Tag>
              </Space>
              <Typography.Paragraph type="secondary" ellipsis={{ rows: 3, expandable: true, symbol: "展开" }} style={{ marginBottom: 0 }}>
                {h.text}
              </Typography.Paragraph>
            </List.Item>
          )}
        />
      )}
    </Card>
  );
}

export function ResourcesPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [uploading, setUploading] = useState(false);
  const [viewing, setViewing] = useState<Resource | null>(null);
  const resources = useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () => unwrap(await api.GET("/api/teacher/resources")),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "pending" || r.status === "parsing") ? 2000 : false),
  });
  const onError = (e: Error) => message.error(e.message);
  const refresh = () => qc.invalidateQueries({ queryKey: QUERY_KEY });

  const patch = useMutation({
    mutationFn: async ({ id, shared }: { id: string; shared: boolean }) =>
      unwrap(await api.PATCH("/api/teacher/resources/{rid}", { params: { path: { rid: id } }, body: { shared } })),
    onSuccess: refresh,
    onError,
  });
  const reparse = useMutation({
    mutationFn: async (id: string) => unwrap(await api.POST("/api/teacher/resources/{rid}/reparse", { params: { path: { rid: id } } })),
    onSuccess: refresh,
    onError,
  });
  const remove = useMutation({
    mutationFn: async (id: string) => unwrap(await api.DELETE("/api/teacher/resources/{rid}", { params: { path: { rid: id } } })),
    onSuccess: () => {
      message.success("已删除");
      refresh();
    },
    onError,
  });

  return (
    <>
      <PageHead
        title="资料库"
        extra={
          <Button type="primary" icon={<CloudUploadOutlined />} onClick={() => setUploading(true)}>
            上传资料
          </Button>
        }
      />
      <Alert
        type="info"
        showIcon
        title="把教案、课件、试卷传上来，AI 生成教案时会自动参考相关内容，并标注出处"
        style={{ marginBottom: 16 }}
      />
      <SearchBox />
      <Table
        rowKey="id"
        loading={resources.isLoading}
        dataSource={resources.data}
        scroll={{ x: 900 }}
        locale={{ emptyText: <Empty description="还没有资料，点右上角上传" /> }}
        columns={[
          {
            title: "文件",
            dataIndex: "filename",
            render: (name: string, r) => (
              <Space orientation="vertical" size={0}>
                <Typography.Link onClick={() => setViewing(r)}>{name}</Typography.Link>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {formatSize(r.size)}
                  {r.status === "ready" && `${r.pages ? ` · ${r.pages} 页` : ""} · ${r.chunk_count} 个片段`}
                  {!r.mine && ` · ${r.owner_name} 共享`}
                </Typography.Text>
              </Space>
            ),
          },
          { title: "学科", dataIndex: "subject", width: 90, render: (s: string | null) => s ?? "不限" },
          { title: "状态", width: 120, render: (_, r) => <StatusCell r={r} /> },
          {
            title: "共享",
            width: 80,
            render: (_, r) =>
              r.mine ? (
                <Switch size="small" checked={r.shared} onChange={(shared) => patch.mutate({ id: r.id, shared })} aria-label="共享给本机构老师" />
              ) : (
                <Tag>他人共享</Tag>
              ),
          },
          { title: "上传时间", dataIndex: "created_at", width: 120, render: (t: string) => dayjs(t).format("MM-DD HH:mm") },
          {
            title: "操作",
            width: 150,
            render: (_, r) => (
              <Space size={0}>
                <Tooltip title="下载原文件">
                  <Button
                    type="text"
                    size="small"
                    icon={<DownloadOutlined />}
                    aria-label="下载原文件"
                    onClick={() => downloadFile(`/api/teacher/resources/${r.id}/file`, r.filename).catch(onError)}
                  />
                </Tooltip>
                {r.mine && (
                  <Tooltip title="重新解析">
                    <Button
                      type="text"
                      size="small"
                      icon={<ReloadOutlined />}
                      aria-label="重新解析"
                      disabled={r.status === "pending" || r.status === "parsing"}
                      onClick={() => reparse.mutate(r.id)}
                    />
                  </Tooltip>
                )}
                {r.mine && (
                  <Popconfirm title={`删除「${r.filename}」？`} description="已经生成的教案不受影响" onConfirm={() => remove.mutate(r.id)}>
                    <Button type="text" size="small" danger icon={<DeleteOutlined />} aria-label="删除" />
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]}
      />
      <UploadModal
        open={uploading}
        onClose={() => {
          setUploading(false);
          refresh();
        }}
      />
      <ResourceDrawer resource={viewing} onClose={() => setViewing(null)} />
    </>
  );
}
