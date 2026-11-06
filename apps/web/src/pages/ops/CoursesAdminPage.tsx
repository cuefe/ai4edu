import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Popconfirm, Space, Table, Tag, Typography } from "antd";
import { useNavigate } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { PageHead } from "@/components/PageHead";

/** 教材内容：内容用命令行离线导入（content-gen、content-import），这里抽检和发布。 */
export function CoursesAdminPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const catalog = useQuery({ queryKey: ["courses"], queryFn: async () => unwrap(await api.GET("/api/courses")) });
  const setStatus = useMutation({
    mutationFn: async ({ id, published }: { id: string; published: boolean }) =>
      unwrap(await api.PUT("/api/courses/{book_id}/status", { params: { path: { book_id: id } }, body: { published } })),
    onSuccess: (b) => {
      message.success(b.status === "published" ? "已发布，学生和老师现在能看到" : "已下架");
      qc.invalidateQueries({ queryKey: ["courses"] });
    },
    onError: (e) => message.error(e.message),
  });

  return (
    <>
      <PageHead title="教材内容" />
      <Typography.Paragraph type="secondary">
        内容用命令行生成和导入。导入后默认是草稿，只有运营能看到；抽检没问题再发布。
      </Typography.Paragraph>
      <Table<Schemas["BookBrief"]>
        rowKey="id"
        size="middle"
        loading={catalog.isLoading}
        dataSource={catalog.data?.books ?? []}
        pagination={false}
        scroll={{ x: 800 }}
        columns={[
          { title: "年级", dataIndex: "grade", width: 72 },
          { title: "学科", dataIndex: "subject", width: 96 },
          { title: "册", dataIndex: "title" },
          { title: "版本", dataIndex: "edition" },
          { title: "章 / 节", width: 80, render: (_, b) => `${b.chapter_count} / ${b.section_count}` },
          { title: "知识点", dataIndex: "kp_count", width: 80 },
          { title: "文件", dataIndex: "file_count", width: 64 },
          {
            title: "状态",
            dataIndex: "status",
            width: 80,
            render: (s: string) => (s === "published" ? <Tag color="green">已发布</Tag> : <Tag color="orange">草稿</Tag>),
          },
          {
            title: "操作",
            width: 160,
            render: (_, b) => (
              <Space>
                <a onClick={() => navigate(`/ops/courses/${b.id}`)}>查看</a>
                <a onClick={() => navigate(`/ops/courses/${b.id}/questions`)}>题库</a>
                {b.status === "published" ? (
                  <Popconfirm title="下架后学生和老师就看不到了" onConfirm={() => setStatus.mutate({ id: b.id, published: false })}>
                    <Button type="link" size="small" style={{ paddingInline: 0 }}>
                      下架
                    </Button>
                  </Popconfirm>
                ) : (
                  <Button type="link" size="small" style={{ paddingInline: 0 }} onClick={() => setStatus.mutate({ id: b.id, published: true })}>
                    发布
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
    </>
  );
}
