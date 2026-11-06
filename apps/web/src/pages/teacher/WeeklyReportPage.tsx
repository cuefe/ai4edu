import { ArrowLeftOutlined, CheckOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Badge, Button, Card, Empty, Popconfirm, Result, Select, Space, Spin, Table, Tabs, Tag, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";
import { GradingCard } from "./AssignmentReportPage";

type StudentRow = Schemas["StudentWeekRow"];

const LEVEL_COLOR: Record<number, string> = { 1: "green", 2: "blue", 3: "purple" };
const STATUS: Record<string, { color: string; label: string }> = {
  todo: { color: "default", label: "未提交" },
  submitted: { color: "orange", label: "待批改" },
  graded: { color: "green", label: "已批改" },
};

function weekLabel(week: string) {
  const start = dayjs(week);
  return `${start.format("M 月 D 日")}这周`;
}

function WeakList({ points }: { points: Schemas["KpMastery"][] }) {
  if (points.length === 0) return <Typography.Text type="secondary">—</Typography.Text>;
  return (
    <Space size={[4, 4]} wrap>
      {points.map((k) => (
        <Tooltip key={k.kp_id} title={`${k.section_no}，掌握度 ${Math.round(k.mastery * 100)}%`}>
          <Tag color="red">
            <MarkdownView text={k.name} inline />
          </Tag>
        </Tooltip>
      ))}
    </Space>
  );
}

export function WeeklyReportPage() {
  const { classId = "" } = useParams();
  const [params] = useSearchParams();
  const subject = params.get("subject") ?? "";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [week, setWeek] = useState<string>();
  const report = useQuery({
    queryKey: ["teacher", "weekly", classId, subject, week],
    queryFn: async () =>
      unwrap(await api.GET("/api/teacher/weekly/classes/{klass_id}/report", { params: { path: { klass_id: classId }, query: { subject, week: week ?? null } } })),
  });
  const grading = useQuery({
    queryKey: ["teacher", "weekly", classId, subject, "grading"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/weekly/classes/{klass_id}/grading", { params: { path: { klass_id: classId }, query: { subject } } })),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "grading") ? 3000 : false),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["teacher", "weekly", classId, subject] });
  const confirmAll = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/teacher/weekly/classes/{klass_id}/confirm-all", { params: { path: { klass_id: classId }, query: { subject } } })),
    onSuccess: (r) => {
      message.success(`已确认 ${r.count} 道`);
      refresh();
    },
    onError: (e) => message.error(e.message),
  });

  if (report.isLoading) return <Spin style={{ display: "block", marginTop: 96 }} />;
  const r = report.data;
  if (!r) return <Result status="404" title={report.error?.message ?? "没有找到这个班"} extra={<Button onClick={() => navigate("/teacher/weekly")}>返回</Button>} />;
  const rows = grading.data ?? [];

  return (
    <>
      <div className="page-head">
        <Space>
          <Button type="text" icon={<ArrowLeftOutlined />} aria-label="返回" onClick={() => navigate("/teacher/weekly")} />
          <Typography.Title level={4} style={{ margin: 0 }}>
            {r.class_name} {r.subject}周测
          </Typography.Title>
        </Space>
        {r.weeks.length > 0 && <Select value={r.week_start} onChange={setWeek} style={{ width: 160 }} options={r.weeks.map((w) => ({ value: w, label: weekLabel(w) }))} />}
      </div>
      {r.class_weak_kps.length > 0 && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space wrap>
            <Typography.Text strong>全班薄弱知识点：</Typography.Text>
            <WeakList points={r.class_weak_kps} />
          </Space>
        </Card>
      )}
      <Tabs
        defaultActiveKey="students"
        items={[
          {
            key: "students",
            label: "学生",
            children: (
              <Table<StudentRow>
                rowKey="student_id"
                size="small"
                dataSource={r.rows}
                pagination={false}
                scroll={{ x: 820 }}
                locale={{ emptyText: <Empty description="这周还没有发周测" /> }}
                columns={[
                  { title: "学生", width: 150, render: (_, s) => `${s.student_name}${s.username ? `（${s.username}）` : ""}` },
                  {
                    title: "难度",
                    width: 80,
                    render: (_, s) =>
                      s.level ? (
                        <Tooltip title={s.reason}>
                          <Tag color={LEVEL_COLOR[s.level]}>{s.level_label}</Tag>
                        </Tooltip>
                      ) : (
                        "—"
                      ),
                  },
                  {
                    title: "状态",
                    width: 100,
                    render: (_, s) => (s.status ? <Tag color={STATUS[s.status].color}>{STATUS[s.status].label}</Tag> : <Tag>没发卷</Tag>),
                  },
                  { title: "得分率", width: 90, render: (_, s) => (s.percent == null ? "—" : `${s.percent}%`) },
                  { title: "上一份", width: 90, render: (_, s) => (s.prev_percent == null ? "—" : `${s.prev_percent}%`) },
                  { title: "薄弱知识点", render: (_, s) => <WeakList points={s.weak_kps} /> },
                  { title: "", width: 70, render: (_, s) => s.assignment_id && <Link to={`/teacher/assignments/${s.assignment_id}`}>看卷子</Link> },
                ]}
              />
            ),
          },
          {
            key: "grading",
            label: (
              <Space size={6}>
                批改确认
                {rows.length > 0 && <Badge count={rows.length} color="#fa8c16" />}
              </Space>
            ),
            children: (
              <>
                {rows.length === 0 ? (
                  <Empty description="没有等待确认的批改。解答题提交后 AI 先批改，再由你确认" />
                ) : (
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Typography.Text type="secondary">AI 没把握的排在前面。确认后学生才能看到分数和评语。</Typography.Text>
                    <Popconfirm title="所有 AI 已批改的题都按 AI 给的分确认？" onConfirm={() => confirmAll.mutate()}>
                      <Button icon={<CheckOutlined />} loading={confirmAll.isPending}>
                        全部按 AI 给分确认
                      </Button>
                    </Popconfirm>
                  </Space>
                )}
                {rows.map((row) => (
                  <GradingCard key={row.id} row={row} onDone={refresh} />
                ))}
              </>
            ),
          },
        ]}
      />
    </>
  );
}
