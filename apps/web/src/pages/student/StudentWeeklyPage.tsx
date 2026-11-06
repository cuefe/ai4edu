import { RightOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Col, Empty, Progress, Row, Space, Spin, Statistic, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useNavigate } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";
import { PageHead } from "@/components/PageHead";
import { StudentPage } from "./StudentHome";

const LEVEL_COLOR: Record<number, string> = { 1: "green", 2: "blue", 3: "purple" };
const STATUS: Record<string, { color: string; label: string }> = {
  todo: { color: "blue", label: "待完成" },
  submitted: { color: "orange", label: "老师批改中" },
  graded: { color: "green", label: "已批改" },
};

function WeekLine({ w, onClick }: { w: Schemas["WeekRow"]; onClick: () => void }) {
  return (
    <div className="task-row" onClick={onClick}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Space wrap>
          <Typography.Text strong>{dayjs(w.week_start).format("M 月 D 日")}这周</Typography.Text>
          <Tag color={STATUS[w.status].color}>{STATUS[w.status].label}</Tag>
          <Tag color={LEVEL_COLOR[w.level]}>{w.level_label}难度</Tag>
          {w.percent != null && <Tag color="green">{w.status === "graded" ? `${w.score} / ${w.total_score} 分` : `已出分的题得分率 ${w.percent}%`}</Tag>}
        </Space>
        <div>
          <Typography.Text type="secondary">{w.reason}</Typography.Text>
        </div>
      </div>
      <RightOutlined />
    </div>
  );
}

function SubjectCard({ s }: { s: Schemas["SubjectWeekly"] }) {
  const navigate = useNavigate();
  const todo = s.weeks.find((w) => w.status === "todo");
  const open = (id: string) => navigate(`/student/assignments/${id}`);
  const masteredShare = s.tested_kps ? Math.round((s.mastered_kps / s.tested_kps) * 100) : 0;
  return (
    <Card
      title={
        <Space wrap>
          {s.subject}
          <Typography.Text type="secondary" style={{ fontWeight: 400 }}>
            {s.book_title}
          </Typography.Text>
        </Space>
      }
      extra={todo && <Button type="primary" onClick={() => open(todo.assignment_id)}>去做本周周测</Button>}
      style={{ marginBottom: 16 }}
    >
      <Row gutter={[16, 16]} style={{ marginBottom: 12 }}>
        <Col xs={12} md={6}>
          <Statistic title="当前难度" value={s.level_label} />
        </Col>
        <Col xs={12} md={6}>
          <Statistic title="考过的知识点" value={s.tested_kps} suffix="个" />
        </Col>
        <Col xs={24} md={12}>
          <Typography.Text type="secondary">已掌握 {s.mastered_kps} 个</Typography.Text>
          <Progress percent={masteredShare} />
        </Col>
      </Row>
      {s.weak_kps.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Typography.Text strong>要加强的知识点：</Typography.Text>
          <Space size={[4, 4]} wrap style={{ marginInlineStart: 8 }}>
            {s.weak_kps.map((k) => (
              <Tag key={k.kp_id} color="red">
                {k.section_no} <MarkdownView text={k.name} inline />
              </Tag>
            ))}
          </Space>
        </div>
      )}
      {s.weeks.map((w) => (
        <WeekLine key={w.assignment_id} w={w} onClick={() => open(w.assignment_id)} />
      ))}
    </Card>
  );
}

export function StudentWeeklyPage() {
  const list = useQuery({ queryKey: ["student", "weekly"], queryFn: async () => unwrap(await api.GET("/api/student/weekly")) });
  return (
    <StudentPage>
      <PageHead title="周测" />
      <Typography.Paragraph type="secondary">每周一份专门给你的卷子：考这周学的内容，也会巩固你的薄弱点。这周考得好，下周难度就升一档。</Typography.Paragraph>
      <Spin spinning={list.isLoading}>
        {list.data?.length === 0 && <Empty description="老师还没有发周测" />}
        {list.data?.map((s) => <SubjectCard key={s.subject} s={s} />)}
      </Spin>
    </StudentPage>
  );
}
