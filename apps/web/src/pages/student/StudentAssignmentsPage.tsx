import { useQuery } from "@tanstack/react-query";
import { Card, Empty, Segmented, Spin } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { AssignmentRow, StudentPage } from "./StudentHome";

export function StudentAssignmentsPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<"todo" | "done">("todo");
  const list = useQuery({ queryKey: ["student", "assignments"], queryFn: async () => unwrap(await api.GET("/api/student/assignments")) });
  const rows = (list.data ?? []).filter((a) => (tab === "todo" ? a.status === "todo" : a.status !== "todo"));
  return (
    <StudentPage>
      <PageHead
        title="作业"
        extra={
          <Segmented
            value={tab}
            onChange={(v) => setTab(v as "todo" | "done")}
            options={[
              { value: "todo", label: "待完成" },
              { value: "done", label: "已提交" },
            ]}
          />
        }
      />
      <Card>
        <Spin spinning={list.isLoading}>
          {rows.length === 0 && <Empty description={tab === "todo" ? "作业都完成啦" : "还没有提交过作业"} />}
          {rows.map((a) => (
            <AssignmentRow key={a.id} a={a} onClick={() => navigate(`/student/assignments/${a.id}`)} />
          ))}
        </Spin>
      </Card>
    </StudentPage>
  );
}
