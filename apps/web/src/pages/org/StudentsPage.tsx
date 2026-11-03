import { DownloadOutlined, InboxOutlined, PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, Upload } from "antd";
import { useState } from "react";
import { ApiError, api, authFetch, downloadFile, saveBlob, unwrap, type Schemas } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { showPassword } from "@/components/showPassword";
import { ToggleActive } from "./ToggleActive";

type UserOut = Schemas["UserOut"];
type ImportResult = Schemas["ImportResultOut"];
type StudentIn = Schemas["StudentIn"];

async function importStudents(file: File): Promise<ImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await authFetch(new Request("/api/org/students/import", { method: "POST", body: fd }));
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(data.message ?? "导入失败", resp.status, data.code);
  return data as ImportResult;
}

function downloadCredentials(result: ImportResult) {
  const esc = (s: string) => `"${s.replaceAll('"', '""')}"`;
  const lines = [["姓名", "学号", "班级", "初始密码"], ...result.credentials.map((c) => [c.name, c.username, c.class_name ?? "", c.password])];
  // 带 BOM，Excel 打开不乱码
  const csv = "﻿" + lines.map((l) => l.map(esc).join(",")).join("\r\n");
  saveBlob(new Blob([csv], { type: "text/csv;charset=utf-8" }), "学生账号密码.csv");
}

function ImportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [result, setResult] = useState<ImportResult | null>(null);
  const run = useMutation({
    mutationFn: importStudents,
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ["org"] });
    },
    onError: (e) => message.error(e.message),
  });

  function close() {
    setResult(null);
    onClose();
  }

  return (
    <Modal title="批量导入学生" open={open} onCancel={close} footer={null} width={640} destroyOnHidden>
      {!result ? (
        <>
          <Typography.Paragraph>
            先下载模板，按模板填写姓名、学号、班级。学号就是学生的登录账号；初始密码不填会自动生成。
          </Typography.Paragraph>
          <Button
            icon={<DownloadOutlined />}
            style={{ marginBottom: 16 }}
            onClick={() => downloadFile("/api/org/students/import-template", "学生导入模板.xlsx").catch((e) => message.error(e.message))}
          >
            下载模板
          </Button>
          <Upload.Dragger
            accept=".xlsx"
            maxCount={1}
            showUploadList={false}
            disabled={run.isPending}
            beforeUpload={(file) => {
              run.mutate(file);
              return false;
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">{run.isPending ? "正在导入…" : "点击或拖拽 Excel 文件到这里"}</p>
            <p className="ant-upload-hint">仅支持 .xlsx，最多 2000 行</p>
          </Upload.Dragger>
        </>
      ) : (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Alert
            type={result.errors.length ? "warning" : "success"}
            showIcon
            title={`成功导入 ${result.created} 人${result.skipped ? `，跳过 ${result.skipped} 人（学号已存在）` : ""}`}
          />
          {result.credentials.length > 0 && (
            <Alert
              type="info"
              showIcon
              title="账号密码只显示这一次，请下载保存后发给学生"
              action={
                <Button size="small" type="primary" onClick={() => downloadCredentials(result)}>
                  下载账号密码
                </Button>
              }
            />
          )}
          {result.errors.length > 0 && (
            <Table
              size="small"
              rowKey={(e) => `${e.row}-${e.message}`}
              dataSource={result.errors}
              pagination={{ pageSize: 8, hideOnSinglePage: true }}
              columns={[
                { title: "行号", dataIndex: "row", width: 80 },
                { title: "问题", dataIndex: "message" },
              ]}
            />
          )}
          <div style={{ textAlign: "right" }}>
            <Button onClick={close}>完成</Button>
          </div>
        </Space>
      )}
    </Modal>
  );
}

export function StudentsPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const [classId, setClassId] = useState<string>();
  const [q, setQ] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [form] = Form.useForm<StudentIn>();

  const classes = useQuery({
    queryKey: ["org", "classes"],
    queryFn: async () => unwrap(await api.GET("/api/org/classes")),
  });
  const students = useQuery({
    queryKey: ["org", "students", classId, q],
    queryFn: async () =>
      unwrap(await api.GET("/api/org/students", { params: { query: { class_id: classId, q: q || undefined } } })),
  });
  const classOptions = (classes.data ?? []).map((c) => ({ value: c.id, label: c.name }));

  const create = useMutation({
    mutationFn: async (v: StudentIn) =>
      unwrap(await api.POST("/api/org/students", { body: { ...v, password: v.password || null } })),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["org"] });
      setCreateOpen(false);
      if (r.initial_password) showPassword(modal, "已添加学生", r.user.name, r.initial_password);
      else message.success("已添加学生");
    },
    onError: (e) => message.error(e.message),
  });

  const reset = useMutation({
    mutationFn: async (u: UserOut) =>
      unwrap(await api.POST("/api/org/users/{user_id}/reset-password", { params: { path: { user_id: u.id } } })),
    onSuccess: (r, u) => showPassword(modal, "密码已重置", u.name, r.password),
    onError: (e) => message.error(e.message),
  });

  return (
    <>
      <PageHead
        title="学生"
        extra={
          <Space wrap>
            <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>
              批量导入
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              添加学生
            </Button>
          </Space>
        }
      />
      <Space wrap style={{ marginBottom: 16 }}>
        <Select allowClear placeholder="全部班级" style={{ width: 180 }} value={classId} onChange={setClassId} options={classOptions} />
        <Input.Search placeholder="姓名或学号" allowClear onSearch={setQ} style={{ width: 220 }} />
      </Space>
      <Table
        rowKey="id"
        loading={students.isLoading}
        dataSource={students.data}
        scroll={{ x: 480 }}
        columns={[
          { title: "学号", dataIndex: "username" },
          { title: "姓名", dataIndex: "name" },
          { title: "状态", dataIndex: "active", render: (a) => (a ? <Tag color="green">正常</Tag> : <Tag>停用</Tag>) },
          {
            title: "操作",
            width: 160,
            render: (_, u) => (
              <Space size={0}>
                <Popconfirm title={`重置 ${u.name} 的密码？`} onConfirm={() => reset.mutate(u)}>
                  <Button type="link" size="small">
                    重置密码
                  </Button>
                </Popconfirm>
                <ToggleActive user={u} />
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title="添加学生"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(v) => create.mutate(v)}>
          <Form.Item name="name" label="姓名" rules={[{ required: true, message: "请输入姓名" }]}>
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item
            name="username"
            label="学号（登录账号）"
            rules={[
              { required: true, message: "请输入学号" },
              { pattern: /^[A-Za-z0-9_-]+$/, message: "只能用字母、数字、下划线和减号" },
            ]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="class_id" label="班级">
            <Select allowClear options={classOptions} />
          </Form.Item>
          <Form.Item name="password" label="初始密码" extra="不填会自动生成" rules={[{ min: 6, message: "至少 6 位" }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} />
    </>
  );
}
