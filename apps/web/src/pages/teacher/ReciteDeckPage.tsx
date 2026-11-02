import { ArrowLeftOutlined, DeleteOutlined, EditOutlined, EyeInvisibleOutlined, PlusOutlined, SaveOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Empty, Form, Input, Modal, Radio, Result, Row, Space, Spin, Switch, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";

type Card = Schemas["Card"];
type DeckOut = Schemas["DeckOut"];
type EditingCard = Card & { key: number };

const CLOZE = /\{\{(.+?)\}\}/gs;
const KIND_LABEL = { qa: "问答", cloze: "挖空" } as const;

/** 挖空卡的正面：自测时把空换成横线，否则把要背的部分加粗标出。 */
function clozeText(front: string, hidden: boolean) {
  return front.replace(CLOZE, (_, x: string) => (hidden ? "＿＿＿＿" : `**${x.trim()}**`));
}

function CardFace({ card, testing }: { card: Card; testing: boolean }) {
  const [revealed, setRevealed] = useState(false);
  useEffect(() => setRevealed(false), [testing]);
  const hidden = testing && !revealed;
  return (
    <div className="recite-card" onClick={() => testing && setRevealed((r) => !r)} style={{ cursor: testing ? "pointer" : undefined }}>
      {card.kind === "cloze" ? (
        <>
          <MarkdownView text={clozeText(card.front, hidden)} />
          {card.back && !hidden && <Typography.Text type="secondary">{card.back}</Typography.Text>}
        </>
      ) : (
        <>
          <MarkdownView text={card.front} />
          <div className="recite-answer">{hidden ? <Typography.Text type="secondary">点一下看答案</Typography.Text> : <MarkdownView text={card.back} />}</div>
        </>
      )}
    </div>
  );
}

function CardModal({ card, onSave, onClose }: { card: EditingCard | null; onSave: (c: EditingCard) => void; onClose: () => void }) {
  const [form] = Form.useForm<Card>();
  const kind = Form.useWatch("kind", form);
  const front = Form.useWatch("front", form) ?? "";
  const back = Form.useWatch("back", form) ?? "";
  useEffect(() => {
    if (card) form.setFieldsValue(card);
  }, [card, form]);
  return (
    <Modal
      title={card?.front ? "修改卡片" : "添加卡片"}
      open={Boolean(card)}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
      width={600}
    >
      <Form form={form} layout="vertical" onFinish={(v) => card && onSave({ ...v, back: v.back ?? "", key: card.key })}>
        <Form.Item name="kind" label="卡片类型">
          <Radio.Group
            optionType="button"
            options={[
              { value: "cloze", label: "挖空卡" },
              { value: "qa", label: "问答卡" },
            ]}
          />
        </Form.Item>
        <Form.Item
          name="front"
          label={kind === "cloze" ? "句子" : "问题"}
          extra={kind === "cloze" ? "把要背的部分用 {{ }} 括起来，例如：{{整数}}和{{分数}}统称为有理数" : "公式用 $...$，例如 $|-3|$"}
          rules={[
            { required: true, whitespace: true, message: "请填写内容" },
            {
              validator: (_, v: string) =>
                kind !== "cloze" || /\{\{.+?\}\}/s.test(v ?? "") ? Promise.resolve() : Promise.reject(new Error("挖空卡要用 {{ }} 标出要背的内容")),
            },
          ]}
        >
          <Input.TextArea rows={3} maxLength={500} showCount />
        </Form.Item>
        <Form.Item
          name="back"
          label={kind === "cloze" ? "提示（选填）" : "答案"}
          rules={kind === "qa" ? [{ required: true, whitespace: true, message: "请填写答案" }] : []}
        >
          <Input.TextArea rows={2} maxLength={500} showCount />
        </Form.Item>
        {front.trim() && (
          <>
            <Typography.Text type="secondary">预览</Typography.Text>
            <CardFace card={{ kind: kind ?? "qa", front, back }} testing={false} />
          </>
        )}
      </Form>
    </Modal>
  );
}

export function ReciteDeckPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["teacher", "recite-deck", id],
    queryFn: async () => unwrap(await api.GET("/api/teacher/recite-decks/{deck_id}", { params: { path: { deck_id: id } } })),
    refetchOnWindowFocus: false, // 编辑中不能被后台刷新覆盖
  });
  if (query.isLoading) return <Spin style={{ display: "block", marginTop: 96 }} />;
  if (!query.data) {
    return (
      <Result
        status="404"
        title={query.error?.message ?? "卡片组不存在"}
        extra={<Button onClick={() => navigate("/teacher/recite")}>返回背诵卡片</Button>}
      />
    );
  }
  return <DeckEditor key={query.data.id} deck={query.data} />;
}

function DeckEditor({ deck }: { deck: DeckOut }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const nextKey = useRef(deck.cards.length);
  const [title, setTitle] = useState(deck.title);
  const [cards, setCards] = useState<EditingCard[]>(() => deck.cards.map((c, i) => ({ kind: c.kind, front: c.front, back: c.back, key: i })));
  const [dirty, setDirty] = useState(false);
  const [editing, setEditing] = useState<EditingCard | null>(null);
  const [testing, setTesting] = useState(false);
  const [showWarnings, setShowWarnings] = useState(true);

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/teacher/recite-decks/{deck_id}", {
          params: { path: { deck_id: deck.id } },
          body: { title: title.trim() || deck.title, cards: cards.map(({ kind, front, back }) => ({ kind, front, back })) },
        }),
      ),
    onSuccess: (out) => {
      setDirty(false);
      message.success("已保存");
      qc.setQueryData(["teacher", "recite-deck", deck.id], out);
      qc.invalidateQueries({ queryKey: ["teacher", "recite-decks"] });
    },
    onError: (e) => message.error(e.message),
  });

  const change = (next: EditingCard[]) => {
    setCards(next);
    setDirty(true);
  };

  return (
    <>
      <div className="page-head">
        <div style={{ display: "flex", alignItems: "center", gap: 4, flex: "1 1 320px", minWidth: 0 }}>
          <Button type="text" icon={<ArrowLeftOutlined />} aria-label="返回背诵卡片" onClick={() => navigate("/teacher/recite")} />
          <Input
            value={title}
            variant="borderless"
            maxLength={200}
            aria-label="卡片组名称"
            className="doc-title-input"
            onChange={(e) => {
              setTitle(e.target.value);
              setDirty(true);
            }}
          />
        </div>
        <Space wrap>
          <Space size={4}>
            <Switch size="small" checked={testing} onChange={setTesting} aria-label="自测模式" />
            <Typography.Text>
              <EyeInvisibleOutlined /> 自测模式
            </Typography.Text>
          </Space>
          <Button icon={<PlusOutlined />} onClick={() => setEditing({ kind: "cloze", front: "", back: "", key: nextKey.current++ })}>
            添加卡片
          </Button>
          <Button type="primary" icon={<SaveOutlined />} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
            {dirty ? "保存" : "已保存"}
          </Button>
        </Space>
      </div>
      {showWarnings && deck.warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          closable={{ onClose: () => setShowWarnings(false) }}
          title={deck.warnings.join("；")}
          style={{ marginBottom: 16 }}
        />
      )}
      <Typography.Paragraph type="secondary">
        {deck.subject} · {deck.grade} · {cards.length} 张卡片。{testing ? "点卡片看答案，模拟学生背诵。" : "AI 整理的内容请核对一遍，有问题直接修改。"}
      </Typography.Paragraph>
      {cards.length === 0 && <Empty description="还没有卡片，点右上角添加" />}
      <Row gutter={[16, 16]}>
        {cards.map((card, i) => (
          <Col key={card.key} xs={24} md={12} xl={8}>
            <Card
              size="small"
              title={
                <Space size={6}>
                  <Typography.Text type="secondary">#{i + 1}</Typography.Text>
                  <Tag color={card.kind === "cloze" ? "blue" : "green"}>{KIND_LABEL[card.kind]}</Tag>
                </Space>
              }
              extra={
                <Space size={0}>
                  <Button type="text" size="small" icon={<EditOutlined />} aria-label="修改" onClick={() => setEditing(card)} />
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    aria-label="删除"
                    onClick={() => change(cards.filter((c) => c.key !== card.key))}
                  />
                </Space>
              }
            >
              <CardFace card={card} testing={testing} />
            </Card>
          </Col>
        ))}
      </Row>
      <CardModal
        card={editing}
        onClose={() => setEditing(null)}
        onSave={(c) => {
          const exists = cards.some((x) => x.key === c.key);
          change(exists ? cards.map((x) => (x.key === c.key ? c : x)) : [...cards, c]);
          setEditing(null);
        }}
      />
    </>
  );
}
