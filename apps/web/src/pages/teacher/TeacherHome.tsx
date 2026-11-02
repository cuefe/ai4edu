import { BookOutlined, EditOutlined, FileTextOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Card, Col, Drawer, Empty, Row, Statistic, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { PageHead } from "@/components/PageHead";

type ClassOut = Schemas["ClassOut"];

const COMING = [
  { icon: <EditOutlined />, title: "AI 备课", desc: "上传资料，生成教案、讲义和背诵要点", stage: "M1" },
  { icon: <BookOutlined />, title: "题库与出题", desc: "按知识点出题，自动校验答案后入库", stage: "M1" },
  { icon: <FileTextOutlined />, title: "作业与批改", desc: "布置作业、自动批改、查看作业报告", stage: "M2" },
];

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
      <Typography.Title level={5}>即将上线</Typography.Title>
      <Row gutter={[16, 16]}>
        {COMING.map((c) => (
          <Col key={c.title} xs={24} sm={12} lg={8}>
            <Card>
              <Card.Meta
                avatar={<span style={{ fontSize: 22, color: "#2f6fed" }}>{c.icon}</span>}
                title={
                  <>
                    {c.title} <Tag>{c.stage}</Tag>
                  </>
                }
                description={c.desc}
              />
            </Card>
          </Col>
        ))}
      </Row>
      <Roster klass={viewing} onClose={() => setViewing(null)} />
    </>
  );
}
