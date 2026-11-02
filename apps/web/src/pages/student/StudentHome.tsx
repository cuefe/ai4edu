import { useQuery } from "@tanstack/react-query";
import { Card, ConfigProvider, Empty, Space, Tag, Typography } from "antd";
import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";

/** 学生端：平板为主，整体用大号控件。 */
export function StudentHome() {
  const { me } = useAuth();
  const classes = useQuery({
    queryKey: ["student", "classes"],
    queryFn: async () => unwrap(await api.GET("/api/student/classes")),
  });

  return (
    <ConfigProvider componentSize="large">
      <Space orientation="vertical" size="large" style={{ width: "100%", maxWidth: 880 }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            {me?.name}，今天也要加油
          </Typography.Title>
          <Space wrap>
            {classes.data?.map((k) => (
              <Tag key={k.id} color="blue">
                {k.name}
              </Tag>
            ))}
          </Space>
        </div>
        <Card title="今日任务">
          <Empty description="老师还没有布置任务" />
        </Card>
        <Card title="错题本">
          <Empty description="作业功能上线后，做错的题会自动收进这里" />
        </Card>
      </Space>
    </ConfigProvider>
  );
}
