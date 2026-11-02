import { BellOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Empty, Popover, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap } from "@/api/client";

const KEY = ["me", "notifications"];

/** 顶栏的站内信：未读数角标，点开看最近的消息，点一条跳到对应页面。 */
export function NotificationBell() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const list = useQuery({
    queryKey: KEY,
    queryFn: async () => unwrap(await api.GET("/api/me/notifications")),
    refetchInterval: 60_000,
  });
  const read = useMutation({
    mutationFn: async (ids: string[]) => unwrap(await api.POST("/api/me/notifications/read", { body: { ids } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const items = list.data?.items ?? [];

  const content = (
    <div style={{ width: 320, maxHeight: 420, overflowY: "auto" }}>
      {items.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有消息" />
      ) : (
        items.map((n) => (
          <div
            key={n.id}
            className={n.read ? "notice-item" : "notice-item notice-unread"}
            onClick={() => {
              if (!n.read) read.mutate([n.id]);
              setOpen(false);
              if (n.link) navigate(n.link);
            }}
          >
            <Typography.Text strong={!n.read} type={n.kind === "crisis" ? "danger" : undefined}>
              {n.title}
            </Typography.Text>
            {n.body && (
              <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ margin: 0, fontSize: 12 }}>
                {n.body}
              </Typography.Paragraph>
            )}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {dayjs(n.created_at).format("MM-DD HH:mm")}
            </Typography.Text>
          </div>
        ))
      )}
    </div>
  );

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomRight"
      title={
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          消息
          {(list.data?.unread ?? 0) > 0 && (
            <Button type="link" size="small" onClick={() => read.mutate([])}>
              全部已读
            </Button>
          )}
        </div>
      }
      content={content}
    >
      <Badge count={list.data?.unread ?? 0} size="small" offset={[-4, 4]}>
        <Button type="text" icon={<BellOutlined />} aria-label="消息" />
      </Badge>
    </Popover>
  );
}
