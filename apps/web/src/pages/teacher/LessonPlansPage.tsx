import { DeleteOutlined, FileWordOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Empty, Popconfirm, Space, Table, Tag } from "antd";
import dayjs from "dayjs";
import { Link, useNavigate } from "react-router";
import { api, downloadFile, unwrap } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { STATUS_TAG } from "./lessonPlanOptions";

export function exportDocx(id: string, title: string) {
  return downloadFile(`/api/teacher/documents/${id}/docx`, `${title}.docx`);
}

export function LessonPlansPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const docs = useQuery({
    queryKey: ["teacher", "documents"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/documents", { params: { query: { doc_type: "lesson_plan" } } })),
    // 有教案在生成时定时刷新状态
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === "generating") ? 3000 : false),
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/teacher/documents/{doc_id}", { params: { path: { doc_id: id } } })),
    onSuccess: () => {
      message.success("已删除");
      qc.invalidateQueries({ queryKey: ["teacher", "documents"] });
    },
    onError: (e) => message.error(e.message),
  });

  const create = (
    <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate("/teacher/lesson-plans/new")}>
      AI 生成教案
    </Button>
  );

  return (
    <>
      <PageHead title="教案" extra={create} />
      <Table
        rowKey="id"
        loading={docs.isLoading}
        dataSource={docs.data}
        scroll={{ x: 720 }}
        locale={{ emptyText: <Empty description="还没有教案，点右上角让 AI 帮你写第一份" /> }}
        columns={[
          {
            title: "课题",
            dataIndex: "title",
            render: (title: string, d) => <Link to={`/teacher/lesson-plans/${d.id}`}>{title}</Link>,
          },
          { title: "学科", dataIndex: "subject", width: 80 },
          { title: "年级", dataIndex: "grade", width: 120 },
          {
            title: "状态",
            dataIndex: "status",
            width: 100,
            render: (status: string) => {
              const tag = STATUS_TAG[status];
              return tag ? <Tag color={tag.color}>{tag.label}</Tag> : <Tag>可编辑</Tag>;
            },
          },
          {
            title: "更新时间",
            dataIndex: "updated_at",
            width: 140,
            render: (t: string) => dayjs(t).format("MM-DD HH:mm"),
          },
          {
            title: "操作",
            width: 170,
            render: (_, d) => (
              <Space size={0}>
                <Button
                  type="link"
                  size="small"
                  icon={<FileWordOutlined />}
                  disabled={d.status !== "ready"}
                  onClick={() => exportDocx(d.id, d.title).catch((e) => message.error(e.message))}
                >
                  导出
                </Button>
                <Popconfirm title={`删除「${d.title}」？删除后不能恢复`} onConfirm={() => remove.mutate(d.id)}>
                  <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
    </>
  );
}
