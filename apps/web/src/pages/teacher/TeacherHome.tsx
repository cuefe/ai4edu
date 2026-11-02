import { BookOutlined, CreditCardOutlined, EditOutlined, FileTextOutlined, FolderOpenOutlined, SnippetsOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Card, Col, Drawer, Empty, Row, Statistic, Table, Typography } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { PageHead } from "@/components/PageHead";

type ClassOut = Schemas["ClassOut"];

const TOOLS = [
  { icon: <SnippetsOutlined />, title: "布置作业", desc: "从题库选题，加讲义阅读和背诵；客观题自动判分，解答题 AI 先批改", to: "/teacher/assignments/new" },
  { icon: <EditOutlined />, title: "AI 教案", desc: "填课题，几分钟生成可编辑的教案，导出 Word", to: "/teacher/lesson-plans/new" },
  { icon: <FileTextOutlined />, title: "AI 讲义", desc: "给学生的课堂讲义或复习讲义，标出考点，附练习和答案", to: "/teacher/handouts/new" },
  { icon: <CreditCardOutlined />, title: "背诵卡片", desc: "从讲义里抽取必背内容，做成问答卡和挖空卡", to: "/teacher/recite" },
  { icon: <BookOutlined />, title: "AI 出题", desc: "按知识点、题型、难度出题，自动校验答案，审核后入库", to: "/teacher/questions/new" },
  { icon: <FolderOpenOutlined />, title: "资料库", desc: "上传教案、课件、试卷，AI 备课时自动参考并标注出处", to: "/teacher/resources" },
];

const ICON_STYLE = { fontSize: 22, color: "#2f6fed" };

function Roster({ klass, onClose }: { klass: ClassOut | null; onClose: () => void }) {
  const classId = klass?.id ?? "";
  const roster = useQuery({
    queryKey: ["teacher", "roster", classId],
    enabled: Boolean(klass),
    queryFn: async () =>
      unwrap(await api.GET("/api/teacher/classes/{class_id}/students", { params: { path: { class_id: classId } } })),
  });
  return (
    <Drawer title={klass ? `${klass.name} · 学生名单` : ""} open={Boolean(klass)} onClose={onClose}>
      <Table
        size="small"
        rowKey={(m) => m.user.id}
        loading={roster.isLoading}
        dataSource={roster.data}
        pagination={false}
        columns={[
          { title: "学号", render: (_, m) => m.user.username },
          { title: "姓名", render: (_, m) => m.user.name },
        ]}
      />
    </Drawer>
  );
}

export function TeacherHome() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [viewing, setViewing] = useState<ClassOut | null>(null);
  const classes = useQuery({
    queryKey: ["teacher", "classes"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/classes")),
  });

  return (
    <>
      <PageHead title={`${me?.name ?? ""}，你好`} />
      <Typography.Title level={5}>我任教的班级</Typography.Title>
      {classes.data?.length === 0 && <Empty description="还没有加入任何班级，请联系机构管理员" />}
      <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
        {classes.data?.map((k) => (
          <Col key={k.id} xs={24} sm={12} lg={8}>
            <Card hoverable loading={classes.isLoading} onClick={() => setViewing(k)}>
              <Statistic title={`${k.grade ?? ""} ${k.name}`} value={k.student_count} suffix="名学生" />
            </Card>
          </Col>
        ))}
      </Row>
      <Typography.Title level={5}>教学工具</Typography.Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
        {TOOLS.map((t) => (
          <Col key={t.title} xs={24} sm={12} lg={8}>
            <Card hoverable onClick={() => navigate(t.to)}>
              <Card.Meta avatar={<span style={ICON_STYLE}>{t.icon}</span>} title={t.title} description={t.desc} />
            </Card>
          </Col>
        ))}
      </Row>
      <Roster klass={viewing} onClose={() => setViewing(null)} />
    </>
  );
}
