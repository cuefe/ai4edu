import { CheckCircleOutlined, EyeOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Card, Empty, Progress, Result, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, unwrap, type Schemas } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";
import { PageHead } from "@/components/PageHead";
import { StudentPage } from "./StudentHome";

type ReviewCard = Schemas["ReviewCard"];

const RATINGS = [
  { value: 1, label: "忘了", color: "#ff4d4f" },
  { value: 2, label: "模糊", color: "#fa8c16" },
  { value: 3, label: "记得", color: "#2f6fed" },
  { value: 4, label: "很熟", color: "#52c41a" },
];
const CLOZE = /\{\{(.+?)\}\}/gs;

function face(card: ReviewCard, revealed: boolean) {
  if (card.kind !== "cloze") return card.front;
  return card.front.replace(CLOZE, (_, x: string) => (revealed ? `**${x.trim()}**` : "＿＿＿＿"));
}

/** 背诵：先看正面自己回忆，再翻开对答案，按记得的程度打分，系统按遗忘规律安排下次复习。 */
export function ReviewPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [params] = useSearchParams();
  const itemId = params.get("item") ?? undefined;
  const today = useQuery({
    queryKey: ["student", "review", itemId ?? "all"],
    queryFn: async () => unwrap(await api.GET("/api/student/review/today", { params: { query: { item_id: itemId } } })),
    refetchOnWindowFocus: false,
  });
  const [queue, setQueue] = useState<ReviewCard[] | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [doneCount, setDoneCount] = useState(0);
  const shownAt = useRef(Date.now());

  useEffect(() => {
    if (today.data && queue === null) setQueue(today.data.cards);
  }, [today.data, queue]);

  const rate = useMutation({
    mutationFn: async ({ card, rating }: { card: ReviewCard; rating: number }) =>
      unwrap(
        await api.POST("/api/student/review/{item_id}/{card_key}", {
          params: { path: { item_id: card.item_id, card_key: card.card_key } },
          body: { rating, duration_ms: Date.now() - shownAt.current },
        }),
      ),
    onSuccess: (_, { card, rating }) => {
      // 忘了的卡片放到这一轮末尾再来一遍
      setQueue((q) => {
        const rest = (q ?? []).slice(1);
        return rating === 1 ? [...rest, { ...card, new: false }] : rest;
      });
      if (rating > 1) setDoneCount((n) => n + 1);
      setRevealed(false);
      shownAt.current = Date.now();
      qc.invalidateQueries({ queryKey: ["student", "assignment"] });
    },
    onError: (e) => message.error(e.message),
  });

  if (today.isLoading || queue === null) return <Spin style={{ display: "block", marginTop: 96 }} />;
  const card = queue[0];
  const total = doneCount + queue.length;
  const deck = itemId ? today.data?.decks[0] : undefined;

  return (
    <StudentPage>
      <PageHead title={deck ? `背诵：${deck.title}` : "今日背诵"} />
      {!card ? (
        total === 0 ? (
          <Empty description={today.data?.decks.length ? "今天的卡片都背完了，明天再来复习" : "老师还没有布置背诵任务"} />
        ) : (
          <Result
            status="success"
            icon={<CheckCircleOutlined />}
            title={`背完了 ${doneCount} 张卡片`}
            subTitle="系统会按遗忘规律安排下次复习的时间，到时候首页会提醒你"
            extra={<Button onClick={() => navigate("/student")}>回到首页</Button>}
          />
        )
      ) : (
        <div style={{ maxWidth: 640, margin: "0 auto" }}>
          <Progress percent={Math.round((doneCount / Math.max(total, 1)) * 100)} format={() => `${doneCount}/${total}`} />
          <Card className="review-card" onClick={() => !revealed && setRevealed(true)}>
            <Space size={4} style={{ marginBottom: 12 }}>
              <Tag>{card.deck_title}</Tag>
              {card.new && <Tag color="blue">新卡片</Tag>}
            </Space>
            <div className="recite-card">
              <MarkdownView text={face(card, revealed)} />
              {card.kind === "qa" && revealed && (
                <div className="recite-answer">
                  <MarkdownView text={card.back} />
                </div>
              )}
              {card.kind === "cloze" && revealed && card.back && <Typography.Text type="secondary">{card.back}</Typography.Text>}
            </div>
          </Card>
          {revealed ? (
            <div className="rating-row">
              {RATINGS.map((r) => (
                <Button
                  key={r.value}
                  size="large"
                  style={{ borderColor: r.color, color: r.color }}
                  loading={rate.isPending && rate.variables?.rating === r.value}
                  disabled={rate.isPending}
                  onClick={() => rate.mutate({ card, rating: r.value })}
                >
                  {r.label}
                </Button>
              ))}
            </div>
          ) : (
            <Button type="primary" size="large" block icon={<EyeOutlined />} onClick={() => setRevealed(true)} style={{ marginTop: 16 }}>
              先在心里回忆，再看答案
            </Button>
          )}
        </div>
      )}
    </StudentPage>
  );
}
