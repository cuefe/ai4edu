import { PlusOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Badge, Button, Checkbox, Empty, Input, Pagination, Select, Space, Spin, Tabs } from "antd";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, unwrap } from "@/api/client";
import { PageHead } from "@/components/PageHead";
import { GRADES, SUBJECTS } from "./lessonPlanOptions";
import { DIFFICULTIES, QTYPES, QuestionEditModal, QuestionItem, type QuestionOut } from "./questionUi";

type View = "review" | "bank" | "rejected";
type Filters = { subject?: string; grade?: string; qtype?: string; difficulty?: string; keyword?: string; mine?: boolean };

const PAGE_SIZE = 10;
const EMPTY: Record<View, string> = {
  review: "没有待审核的题。AI 出的题校验完会出现在这里",
  bank: "题库里还没有题，可以让 AI 出题，或者手动录题",
  rejected: "没有驳回的题",
};

export function QuestionsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as View | null) ?? "review";
  const [filters, setFilters] = useState<Filters>({});
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<QuestionOut> | null>(null);

  const counts = useQuery({
    queryKey: ["teacher", "questions", "counts"],
    queryFn: async () => unwrap(await api.GET("/api/teacher/questions/counts")),
  });
  const list = useQuery({
    queryKey: ["teacher", "questions", view, filters, page],
    queryFn: async () =>
      unwrap(await api.GET("/api/teacher/questions", { params: { query: { view, ...filters, page, page_size: PAGE_SIZE } } })),
    // 有题在校验时定时刷新
    refetchInterval: (q) => (q.state.data?.items.some((x) => x.status === "checking") ? 3000 : false),
  });

  const setFilter = (patch: Filters) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };
  const tabLabel = (label: string, n?: number, highlight = false) => (
    <Space size={6}>
      {label}
      {n !== undefined && <Badge count={n} showZero color={highlight && n > 0 ? "#fa541c" : "#bfbfbf"} overflowCount={999} />}
    </Space>
  );

  return (
    <>
      <PageHead
        title="题库"
        extra={
          <Space>
            <Button icon={<PlusOutlined />} onClick={() => setEditing({})}>
              手动录题
            </Button>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => navigate("/teacher/questions/new")}>
              AI 出题
            </Button>
          </Space>
        }
      />
      <Tabs
        activeKey={view}
        onChange={(key) => {
          setParams({ view: key }, { replace: true });
          setPage(1);
        }}
        items={[
          { key: "review", label: tabLabel("待审核", counts.data?.review, true) },
          { key: "bank", label: tabLabel("机构题库", counts.data?.bank) },
          { key: "rejected", label: tabLabel("已驳回", counts.data?.rejected) },
        ]}
      />
      <Space wrap style={{ marginBottom: 16 }}>
        <Select allowClear placeholder="学科" style={{ width: 100 }} options={SUBJECTS.map((s) => ({ value: s, label: s }))} onChange={(subject) => setFilter({ subject })} />
        <Select allowClear placeholder="年级" style={{ width: 130 }} options={GRADES.map((g) => ({ value: g, label: g }))} onChange={(grade) => setFilter({ grade })} />
        <Select allowClear placeholder="题型" style={{ width: 110 }} options={QTYPES.map((t) => ({ value: t, label: t }))} onChange={(qtype) => setFilter({ qtype })} />
        <Select allowClear placeholder="难度" style={{ width: 100 }} options={DIFFICULTIES.map((d) => ({ value: d, label: d }))} onChange={(difficulty) => setFilter({ difficulty })} />
        <Input.Search allowClear placeholder="搜题干、知识点" maxLength={50} style={{ width: 220 }} onSearch={(v) => setFilter({ keyword: v.trim() || undefined })} />
        {view === "bank" && <Checkbox onChange={(e) => setFilter({ mine: e.target.checked || undefined })}>只看我出的</Checkbox>}
      </Space>
      <Spin spinning={list.isLoading}>
        {list.data?.items.length === 0 && <Empty description={EMPTY[view]} style={{ padding: "48px 0" }} />}
        {list.data?.items.map((q) => (
          <div key={q.id} style={{ marginBottom: 12 }}>
            <QuestionItem q={q} onEdit={setEditing} />
          </div>
        ))}
      </Spin>
      {(list.data?.total ?? 0) > PAGE_SIZE && (
        <Pagination
          align="end"
          current={page}
          pageSize={PAGE_SIZE}
          total={list.data?.total}
          onChange={setPage}
          showSizeChanger={false}
          showTotal={(total) => `共 ${total} 道`}
        />
      )}
      <QuestionEditModal question={editing} onClose={() => setEditing(null)} />
    </>
  );
}
