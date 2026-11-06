import { RightOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Card, Empty, Segmented, Space, Spin, Tag, Typography } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { CourseShell } from "./CourseShell";

const ALL = "全部";

export function CoursesPage({ base }: { base: string }) {
  const navigate = useNavigate();
  const catalog = useQuery({ queryKey: ["courses"], queryFn: async () => unwrap(await api.GET("/api/courses")) });
  const [picked, setPicked] = useState<string>();
  const books = catalog.data?.books ?? [];
  const grades = [...new Set(books.map((b) => b.grade))];
  // 默认看自己的年级；自己的年级还没有内容时看全部
  const mine = catalog.data?.my_grades.find((g) => grades.includes(g));
  const grade = picked ?? mine ?? ALL;
  const shown = books.filter((b) => grade === ALL || b.grade === grade);
  const subjects = [...new Set(shown.map((b) => b.subject))];

  return (
    <CourseShell base={base}>
      <PageHead
        title="课程"
        extra={
          grades.length > 0 && (
            <Segmented value={grade} onChange={(v) => setPicked(v as string)} options={[ALL, ...grades]} />
          )
        }
      />
      <Spin spinning={catalog.isLoading}>
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          {!catalog.isLoading && shown.length === 0 && (
            <Card>
              <Empty description="这个年级的课程还在准备中" />
            </Card>
          )}
          {subjects.map((subject) => (
            <Card key={subject} title={subject} size="small">
              {shown
                .filter((b) => b.subject === subject)
                .map((b) => (
                  <BookRow key={b.id} book={b} onClick={() => navigate(`${base}/${b.id}`)} />
                ))}
            </Card>
          ))}
        </Space>
      </Spin>
    </CourseShell>
  );
}

function BookRow({ book, onClick }: { book: Schemas["BookBrief"]; onClick: () => void }) {
  return (
    <div className="task-row" onClick={onClick}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Space wrap>
          <Typography.Text strong>{book.title}</Typography.Text>
          <Tag>{book.grade}</Tag>
          {book.status !== "published" && <Tag color="orange">草稿</Tag>}
        </Space>
        <div>
          <Typography.Text type="secondary">
            {book.edition} · {book.chapter_count} 章 · {book.kp_count} 个知识点
            {book.file_count > 0 && ` · ${book.file_count} 份课本课件`}
          </Typography.Text>
        </div>
      </div>
      <RightOutlined />
    </div>
  );
}
