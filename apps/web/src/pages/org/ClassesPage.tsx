import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag } from "antd";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { PageHead } from "@/components/PageHead";

type ClassOut = Schemas["ClassOut"];

function useClasses() {
  return useQuery({ queryKey: ["org", "classes"], queryFn: async () => unwrap(await api.GET("/api/org/classes")) });
}

function ClassFormModal({ editing, open, onClose }: { editing?: ClassOut; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [form] = Form.useForm<{ name: string; grade?: string }>();
  const save = useMutation({
    mutationFn: async (v: { name: string; grade?: string }) =>
      editing
        ? unwrap(await api.PATCH("/api/org/classes/{class_id}", { params: { path: { class_id: editing.id } }, body: v }))
        : unwrap(await api.POST("/api/org/classes", { body: v })),
    onSuccess: () => {
      message.success("已保存");
      qc.invalidateQueries({ queryKey: ["org", "classes"] });
      onClose();
    },
    onError: (e) => message.error(e.message),
  });

  return (
    <Modal
      title={editing ? "编辑班级" : "新建班级"}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={save.isPending}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={editing ? { name: editing.name, grade: editing.grade ?? undefined } : undefined}
        onFinish={(v) => save.mutate(v)}
      >
        <Form.Item name="name" label="班级名称" rules={[{ required: true, message: "请输入班级名称" }]}>
          <Input placeholder="如：初一(1)班" maxLength={50} />
        </Form.Item>
        <Form.Item name="grade" label="年级">
          <Input placeholder="如：初一" maxLength={20} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function MembersDrawer({ klass, onClose }: { klass: ClassOut | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [teacherId, setTeacherId] = useState<string>();
  const [subject, setSubject] = useState("");
  const classId = klass?.id ?? "";

  const members = useQuery({
    queryKey: ["org", "members", classId],
    enabled: Boolean(klass),
    queryFn: async () =>
      unwrap(await api.GET("/api/org/classes/{class_id}/members", { params: { path: { class_id: classId } } })),
  });
  const teachers = useQuery({
    queryKey: ["org", "teachers"],
    enabled: Boolean(klass),
    queryFn: async () => unwrap(await api.GET("/api/org/teachers")),
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["org", "members", classId] });
    qc.invalidateQueries({ queryKey: ["org", "classes"] });
  };
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/org/classes/{class_id}/members", {
          params: { path: { class_id: classId } },
          body: { user_id: teacherId!, member_role: "teacher", subject: subject || null },
        }),
      ),
    onSuccess: () => {
      setTeacherId(undefined);
      setSubject("");
      refresh();
    },
    onError: (e) => message.error(e.message),
  });
  const remove = useMutation({
    mutationFn: async (userId: string) =>
      unwrap(
        await api.DELETE("/api/org/classes/{class_id}/members/{user_id}", {
          params: { path: { class_id: classId, user_id: userId } },
        }),
      ),
    onSuccess: refresh,
    onError: (e) => message.error(e.message),
  });

  return (
    <Drawer title={klass ? `${klass.name} · 成员` : ""} open={Boolean(klass)} onClose={onClose} size="large">
      <Space.Compact block style={{ marginBottom: 16 }}>
        <Select
          style={{ flex: 1 }}
          placeholder="选择任课老师"
          value={teacherId}
          onChange={setTeacherId}
          showSearch={{ optionFilterProp: "label" }}
          options={(teachers.data ?? []).map((t) => ({ value: t.id, label: `${t.name}（${t.phone_masked ?? ""}）` }))}
        />
        <Input style={{ width: 120 }} placeholder="学科" value={subject} onChange={(e) => setSubject(e.target.value)} />
        <Button type="primary" disabled={!teacherId} loading={add.isPending} onClick={() => add.mutate()}>
          加入
        </Button>
      </Space.Compact>
      <Table
        rowKey={(m) => m.user.id}
        loading={members.isLoading}
        dataSource={members.data}
        pagination={false}
        size="small"
        columns={[
          { title: "姓名", render: (_, m) => m.user.name },
          {
            title: "身份",
            render: (_, m) =>
              m.member_role === "teacher" ? <Tag color="blue">老师{m.subject ? ` · ${m.subject}` : ""}</Tag> : <Tag>学生</Tag>,
          },
          { title: "账号", render: (_, m) => m.user.username ?? m.user.phone_masked },
          {
            title: "",
            align: "right",
            render: (_, m) => (
              <Popconfirm title={`把 ${m.user.name} 移出班级？`} onConfirm={() => remove.mutate(m.user.id)}>
                <Button type="link" danger size="small">
                  移出
                </Button>
              </Popconfirm>
            ),
          },
        ]}
      />
    </Drawer>
  );
}

export function ClassesPage() {
  const classes = useClasses();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<ClassOut>();
  const [viewing, setViewing] = useState<ClassOut | null>(null);

  return (
    <>
      <PageHead
        title="班级"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(undefined);
              setFormOpen(true);
            }}
          >
            新建班级
          </Button>
        }
      />
      <Table
        rowKey="id"
        loading={classes.isLoading}
        dataSource={classes.data}
        scroll={{ x: 560 }}
        columns={[
          { title: "班级", dataIndex: "name" },
          { title: "年级", dataIndex: "grade", render: (g) => g ?? "—" },
          { title: "老师", dataIndex: "teacher_count", width: 80 },
          { title: "学生", dataIndex: "student_count", width: 80 },
          {
            title: "操作",
            width: 160,
            render: (_, k) => (
              <Space>
                <Button type="link" size="small" onClick={() => setViewing(k)}>
                  成员
                </Button>
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    setEditing(k);
                    setFormOpen(true);
                  }}
                >
                  编辑
                </Button>
              </Space>
            ),
          },
        ]}
      />
      <ClassFormModal open={formOpen} editing={editing} onClose={() => setFormOpen(false)} />
      <MembersDrawer klass={viewing} onClose={() => setViewing(null)} />
    </>
  );
}
