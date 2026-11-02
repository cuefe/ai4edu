import { PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Badge, Button, Empty, Progress, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { Link, useNavigate } from "react-router";
import { api, unwrap } from "@/api/client";
import { PageHead } from "@/components/PageHead";

export function AssignmentsPage() {
  const navigate = useNavigate();
  const list = useQuery({
    queryKey: ["teacher", "assignments"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/assignments")),
  });
  return (
    <>
      <PageHead
        title="作业"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate("/teacher/assignments/new")}>
            布置作业
          </Button>
        }
      />
      <Table
        rowKey="id"
        loading={list.isLoading}
        dataSource={list.data}
        scroll={{ x: 820 }}
        locale={{ emptyText: <Empty description="还没有布置过作业。可以从题库选题，也可以布置讲义阅读和背诵" /> }}
        columns={[
          {
            title: "作业",
            dataIndex: "title",
            render: (t: string, a) => (
              <>
                <Link to={`/teacher/assignments/${a.id}`}>{t}</Link>
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {a.subject} · {a.class_names.join("、") || "单独布置"}
                    {!a.allow_ai && " · 不能问 AI"}
                  </Typography.Text>
                </div>
              </>
            ),
          },
          {
            title: "提交",
            width: 160,
            render: (_, a) => (
              <Progress
                percent={Math.round((a.submitted_count / Math.max(a.student_count, 1)) * 100)}
                format={() => `${a.submitted_count}/${a.student_count}`}
                size="small"
              />
            ),
          },
          {
            title: "平均分",
            width: 100,
            render: (_, a) => (a.avg_score == null ? "—" : `${a.avg_score} / ${a.total_score}`),
          },
          {
            title: "待批改",
            dataIndex: "pending_review",
            width: 90,
            render: (n: number) => (n ? <Badge count={n} color="#fa8c16" /> : "—"),
          },
          {
            title: "截止",
            dataIndex: "due_at",
            width: 140,
            render: (t: string | null, a) => {
              if (dayjs(a.publish_at).isAfter(dayjs())) return <Tag color="blue">{dayjs(a.publish_at).format("MM-DD HH:mm")} 发布</Tag>;
              if (!t) return "不限";
              return dayjs(t).isBefore(dayjs()) ? <Tag>已截止</Tag> : dayjs(t).format("MM-DD HH:mm");
            },
          },
        ]}
      />
    </>
  );
}
