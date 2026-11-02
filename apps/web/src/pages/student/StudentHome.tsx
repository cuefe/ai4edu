import { BookOutlined, CreditCardOutlined, MessageOutlined, RightOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Card, Col, ConfigProvider, Empty, Row, Space, Statistic, Tag, Typography } from "antd";
import dayjs from "dayjs";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";

/** 学生端页面统一用大号控件（平板为主）。 */
export function StudentPage({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider componentSize="large">
      <div className="student-page">{children}</div>
    </ConfigProvider>
  );
}

export function dueTag(a: Pick<Schemas["StudentAssignmentBrief"], "due_at" | "status">) {
  if (a.status !== "todo") return a.status === "graded" ? <Tag color="green">已批改</Tag> : <Tag color="orange">老师批改中</Tag>;
  if (!a.due_at) return <Tag color="blue">待完成</Tag>;
  const due = dayjs(a.due_at);
  if (due.isBefore(dayjs())) return <Tag color="red">已截止，可补交</Tag>;
  const hours = due.diff(dayjs(), "hour");
  return <Tag color={hours < 24 ? "orange" : "blue"}>{hours < 24 ? `${Math.max(hours, 1)} 小时后截止` : `${due.format("MM-DD HH:mm")} 截止`}</Tag>;
}

/** “王”→“王老师”；名字本身就是“李老师”的不再重复加。 */
export function teacherLabel(name: string) {
  return name.endsWith("老师") ? name : `${name}老师`;
}

export function AssignmentRow({ a, onClick }: { a: Schemas["StudentAssignmentBrief"]; onClick: () => void }) {
  const parts = [a.question_count && `${a.question_count} 道题`, a.task_count && `${a.task_count} 项阅读背诵`].filter(Boolean);
  return (
    <div className="task-row" onClick={onClick}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Space wrap>
          <Typography.Text strong>{a.title}</Typography.Text>
          {dueTag(a)}
          {a.score != null && <Tag color="green">{a.score} / {a.total_score} 分</Tag>}
        </Space>
        <div>
          <Typography.Text type="secondary">
            {a.subject} · {teacherLabel(a.teacher_name)} · {parts.join("，")}
          </Typography.Text>
        </div>
      </div>
      <RightOutlined />
    </div>
  );
}

function Entry({ icon, title, value, suffix, onClick }: { icon: ReactNode; title: string; value: number | string; suffix?: string; onClick: () => void }) {
  return (
    <Card hoverable onClick={onClick}>
      <Statistic title={<Space>{icon}{title}</Space>} value={value} suffix={suffix} />
    </Card>
  );
}

export function StudentHome() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const assignments = useQuery({ queryKey: ["student", "assignments"], queryFn: async () => unwrap(await api.GET("/api/student/assignments")) });
  const review = useQuery({ queryKey: ["student", "review"], queryFn: async () => unwrap(await api.GET("/api/student/review/today", { params: { query: {} } })) });
  const wrong = useQuery({ queryKey: ["student", "wrong"], queryFn: async () => unwrap(await api.GET("/api/student/wrong-items", { params: { query: {} } })) });
  const classes = useQuery({ queryKey: ["student", "classes"], queryFn: async () => unwrap(await api.GET("/api/student/classes")) });
  const todo = (assignments.data ?? [])
    .filter((a) => a.status === "todo")
    .sort((a, b) => (a.due_at ?? "9").localeCompare(b.due_at ?? "9"));
  const cards = (review.data?.due_count ?? 0) + (review.data?.new_count ?? 0);

  return (
    <StudentPage>
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
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
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={8}>
            <Entry icon={<CreditCardOutlined />} title="今日背诵" value={cards} suffix="张卡片" onClick={() => navigate("/student/review")} />
          </Col>
          <Col xs={24} sm={8}>
            <Entry icon={<BookOutlined />} title="错题待订正" value={wrong.data?.pending ?? 0} suffix="道" onClick={() => navigate("/student/wrong")} />
          </Col>
          <Col xs={24} sm={8}>
            <Entry icon={<MessageOutlined />} title="问一问" value="有问题就问" onClick={() => navigate("/student/tutor")} />
          </Col>
        </Row>
        <Card title="今日任务" loading={assignments.isLoading} extra={<a onClick={() => navigate("/student/assignments")}>全部作业</a>}>
          {todo.length === 0 && <Empty description="作业都完成啦" />}
          {todo.map((a) => (
            <AssignmentRow key={a.id} a={a} onClick={() => navigate(`/student/assignments/${a.id}`)} />
          ))}
        </Card>
      </Space>
    </StudentPage>
  );
}
