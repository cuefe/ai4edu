import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Empty, Grid, Row, Spin, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect } from "react";
import { useNavigate, useParams } from "react-router";
import { api, unwrap } from "@/api/client";
import { TutorChat } from "@/components/TutorChat";
import { StudentPage } from "./StudentHome";

const MODE_TAG: Record<string, { color: string; label: string }> = {
  learn: { color: "blue", label: "学习" },
  homework: { color: "orange", label: "作业" },
  correction: { color: "purple", label: "订正" },
};

/** 问一问：左边是最近的提问，右边是对话。 */
export function TutorPage() {
  const { sid } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const screens = Grid.useBreakpoint();
  const status = useQuery({ queryKey: ["student", "tutor", "status"], queryFn: async () => unwrap(await api.GET("/api/student/tutor/status")) });
  const sessions = useQuery({ queryKey: ["student", "tutor", "sessions"], queryFn: async () => unwrap(await api.GET("/api/student/tutor/sessions")) });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/student/tutor/sessions", { body: { mode: "learn" } })),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["student", "tutor", "sessions"] });
      navigate(`/student/tutor/${s.id}`);
    },
    onError: (e) => message.error(e.message),
  });

  // 没有选会话时：有最近的就打开最近的
  useEffect(() => {
    if (!sid && sessions.data?.length && screens.md) navigate(`/student/tutor/${sessions.data[0].id}`, { replace: true });
  }, [sid, sessions.data, screens.md, navigate]);

  const blocked = status.data?.blocked_by;
  const list = (
    <Card
      size="small"
      title="最近的提问"
      extra={
        <Button type="primary" size="small" icon={<PlusOutlined />} disabled={Boolean(blocked)} loading={create.isPending} onClick={() => create.mutate()}>
          新提问
        </Button>
      }
      styles={{ body: { padding: 0, maxHeight: "calc(100vh - 240px)", overflowY: "auto" } }}
    >
      <Spin spinning={sessions.isLoading}>
        {sessions.data?.length === 0 && <Empty description="还没有提问" style={{ padding: 24 }} />}
        {sessions.data?.map((s) => (
          <div key={s.id} className={s.id === sid ? "session-row session-active" : "session-row"} onClick={() => navigate(`/student/tutor/${s.id}`)}>
            <Tag color={MODE_TAG[s.mode].color}>{MODE_TAG[s.mode].label}</Tag>
            <Typography.Text ellipsis style={{ flex: 1 }}>
              {s.title}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {dayjs(s.updated_at).format("MM-DD")}
            </Typography.Text>
          </div>
        ))}
      </Spin>
    </Card>
  );

  return (
    <StudentPage>
      {blocked && (
        <Alert type="warning" showIcon title={`作业「${blocked}」老师设置了作业期间不能问 AI，提交作业后再来问吧`} style={{ marginBottom: 16 }} />
      )}
      <Row gutter={16}>
        {(screens.md || !sid) && (
          <Col xs={24} md={8} style={{ marginBottom: 16 }}>
            {list}
          </Col>
        )}
        {sid && (
          <Col xs={24} md={16}>
            {!screens.md && (
              <Button type="link" onClick={() => navigate("/student/tutor")} style={{ paddingInline: 0 }}>
                ‹ 最近的提问
              </Button>
            )}
            <Card size="small">
              <TutorChat key={sid} sessionId={sid} />
            </Card>
          </Col>
        )}
      </Row>
    </StudentPage>
  );
}
