import { FilePdfOutlined, MenuOutlined, MessageOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Drawer, Empty, Grid, List, Menu, Modal, Row, Space, Spin, Tabs, Tag, Typography } from "antd";
import { lazy, Suspense, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { api, downloadFile, unwrap, type Schemas } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";
import { PageHead } from "@/components/PageHead";
import { CourseShell } from "./CourseShell";

// 思维导图和 PDF 的库体积较大，打开时才加载
const MindMap = lazy(() => import("@/components/MindMap").then((m) => ({ default: m.MindMap })));
const PdfViewer = lazy(() => import("@/components/PdfViewer").then((m) => ({ default: m.PdfViewer })));

type FileOut = Schemas["FileOut"];
type Kp = Schemas["KpOut"];

const IMPORTANCE_COLOR: Record<string, string> = { 核心: "red", 重点: "orange", 了解: "default" };

function fileSize(bytes: number) {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

function isPdf(f: FileOut) {
  return f.mime === "application/pdf";
}

function KpCard({ kp }: { kp: Kp }) {
  return (
    <div className="kp-card">
      <Space wrap size={[6, 4]} style={{ marginBottom: 4 }}>
        <Typography.Text strong>
          <MarkdownView text={kp.name} inline />
        </Typography.Text>
        <Tag color={IMPORTANCE_COLOR[kp.importance]}>{kp.importance}</Tag>
        <Tag>{kp.kind}</Tag>
        {kp.recite && <Tag color="blue">要背</Tag>}
      </Space>
      <MarkdownView text={kp.content} />
    </div>
  );
}

/** 看整章时，知识点按节分组。 */
function KpList({ points, grouped }: { points: Kp[]; grouped: boolean }) {
  if (points.length === 0) return <Empty description="这部分还没有知识点" />;
  if (!grouped) return points.map((k) => <KpCard key={k.id} kp={k} />);
  const sections = [...new Set(points.map((k) => k.section_no ?? ""))];
  return sections.map((no) => {
    const rows = points.filter((k) => k.section_no === no);
    return (
      <div key={no} style={{ marginBottom: 16 }}>
        <Typography.Title level={5}>
          {no} {rows[0].section_title}
        </Typography.Title>
        {rows.map((k) => (
          <KpCard key={k.id} kp={k} />
        ))}
      </div>
    );
  });
}

function FileList({ files, onOpen }: { files: FileOut[]; onOpen: (f: FileOut) => void }) {
  return (
    <List
      dataSource={files}
      renderItem={(f) => (
        <List.Item
          actions={[
            isPdf(f) ? (
              <a key="open" onClick={() => onOpen(f)}>
                打开
              </a>
            ) : (
              <a key="download" onClick={() => void downloadFile(`/api/courses/files/${f.id}`, f.filename)}>
                下载
              </a>
            ),
          ]}
        >
          <List.Item.Meta avatar={<FilePdfOutlined />} title={f.title} description={fileSize(f.size)} />
        </List.Item>
      )}
    />
  );
}

function ChapterPanel({ id, isChapter, onOpen }: { id: string; isChapter: boolean; onOpen: (f: FileOut) => void }) {
  const detail = useQuery({
    queryKey: ["courses", "chapter", id],
    queryFn: async () => unwrap(await api.GET("/api/courses/chapters/{chapter_id}", { params: { path: { chapter_id: id } } })),
  });
  if (detail.isLoading) return <Spin style={{ display: "block", margin: "48px auto" }} />;
  const c = detail.data;
  if (!c) return <Alert type="error" showIcon title={detail.error?.message ?? "内容不存在"} />;
  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {isChapter ? `第 ${c.no} 章 ${c.title}` : `${c.no} ${c.title}`}
      </Typography.Title>
      {c.summary && <MarkdownView text={c.summary} />}
      <Tabs
        destroyOnHidden
        items={[
          {
            key: "kp",
            label: `知识点（${c.knowledge_points.length}）`,
            children: <KpList points={c.knowledge_points} grouped={isChapter} />,
          },
          {
            key: "map",
            label: "思维导图",
            children: c.mind_map ? (
              <Suspense fallback={<Spin style={{ display: "block", margin: "48px auto" }} />}>
                <MindMap data={c.mind_map} />
              </Suspense>
            ) : (
              <Empty description="这部分还没有思维导图" />
            ),
          },
          ...(c.files.length
            ? [{ key: "files", label: `课件（${c.files.length}）`, children: <FileList files={c.files} onOpen={onOpen} /> }]
            : []),
        ]}
      />
    </Card>
  );
}

export function CourseBookPage({ base }: { base: string }) {
  const { bookId = "" } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const screens = Grid.useBreakpoint();
  const [menuOpen, setMenuOpen] = useState(false);
  const [viewing, setViewing] = useState<FileOut>();
  const book = useQuery({
    queryKey: ["courses", "book", bookId],
    queryFn: async () => unwrap(await api.GET("/api/courses/{book_id}", { params: { path: { book_id: bookId } } })),
  });
  const chapters = book.data?.chapters ?? [];
  const current = params.get("c") ?? chapters[0]?.id ?? "";

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [current]);

  if (book.isLoading) return <Spin style={{ display: "block", marginTop: 96 }} />;
  if (!book.data) return <Alert type="error" showIcon title={book.error?.message ?? "教材不存在"} />;

  const openChapter = chapters.find((c) => c.id === current || c.sections?.some((s) => s.id === current));
  const textbooks = book.data.files.filter((f) => f.kind === "textbook");
  const menu = (
    <Menu
      mode="inline"
      selectedKeys={[current]}
      defaultOpenKeys={openChapter ? [`sub-${openChapter.id}`] : []}
      onClick={({ key }) => {
        setParams({ c: key }, { replace: true });
        setMenuOpen(false);
      }}
      style={{ borderInlineEnd: 0 }}
      items={chapters.map((c) => ({
        key: `sub-${c.id}`,
        label: `第 ${c.no} 章 ${c.title}`,
        title: c.title,
        children: [
          { key: c.id, label: "本章总览" },
          ...(c.sections ?? []).map((s) => ({ key: s.id, label: `${s.no} ${s.title}`, title: s.title })),
        ],
      }))}
    />
  );

  return (
    <CourseShell base={base}>
      <div className="course-page">
        <PageHead
          title={
            <Space wrap>
              <a onClick={() => navigate(base)}>‹</a>
              {book.data.subject} {book.data.title}
              {book.data.status !== "published" && <Tag color="orange">草稿</Tag>}
            </Space>
          }
          extra={
            <Space wrap>
              {textbooks.map((f) => (
                <Button key={f.id} icon={<FilePdfOutlined />} onClick={() => setViewing(f)}>
                  看课本
                </Button>
              ))}
              {base.startsWith("/student") && (
                <Button icon={<MessageOutlined />} onClick={() => navigate("/student/tutor")}>
                  有问题问 AI
                </Button>
              )}
              {!screens.md && (
                <Button icon={<MenuOutlined />} onClick={() => setMenuOpen(true)}>
                  目录
                </Button>
              )}
            </Space>
          }
        />
        <Row gutter={16}>
          {screens.md !== false && (
            <Col md={8} lg={7}>
              <Card size="small" styles={{ body: { padding: 4 } }} className="course-menu">
                {chapters.length ? menu : <Empty description="还没有章节" />}
              </Card>
            </Col>
          )}
          <Col xs={24} md={16} lg={17}>
            {current ? (
              <ChapterPanel
                key={current}
                id={current}
                isChapter={chapters.some((c) => c.id === current)}
                onOpen={setViewing}
              />
            ) : (
              <Card>
                <Empty description="还没有内容" />
              </Card>
            )}
          </Col>
        </Row>
        <Drawer title="目录" placement="left" open={menuOpen} onClose={() => setMenuOpen(false)} styles={{ body: { padding: 8 } }}>
          {menu}
        </Drawer>
        <Modal
          open={Boolean(viewing)}
          title={viewing?.title}
          footer={null}
          width="min(1000px, 96vw)"
          destroyOnHidden
          onCancel={() => setViewing(undefined)}
        >
          {viewing && (
            <Suspense fallback={<Spin style={{ display: "block", margin: "48px auto" }} />}>
              <PdfViewer url={`/api/courses/files/${viewing.id}`} />
            </Suspense>
          )}
        </Modal>
      </div>
    </CourseShell>
  );
}
