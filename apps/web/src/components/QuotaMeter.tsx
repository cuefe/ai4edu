import { ExclamationCircleFilled, StopFilled } from "@ant-design/icons";
import { Progress, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";

// 名额、额度的用量条：填充色表示严重程度（正常 → 快用完 → 用完），没填充的部分用同一色系的浅色，
// 整条都能看出状态；状态另外用图标加文字写出来，不只靠颜色
const LEVELS = [
  { from: 1, stroke: "#d9363e", rail: "#fde2e1", text: "已用完", icon: <StopFilled style={{ color: "#d9363e" }} /> },
  {
    from: 0.8,
    stroke: "#d48806",
    rail: "#fdf0cf",
    text: "快用完了",
    icon: <ExclamationCircleFilled style={{ color: "#d48806" }} />,
  },
  { from: 0, stroke: "#2f6fed", rail: "#dce7fc", text: "", icon: null },
];

export function quotaLevel(used: number, quota: number | null | undefined) {
  if (quota == null) return null;
  const ratio = quota > 0 ? used / quota : 1;
  return { ratio, ...LEVELS.find((l) => ratio >= l.from)! };
}

export function QuotaMeter({
  label,
  used,
  quota,
  format = (n) => String(n),
  compact = false,
}: {
  label?: string;
  used: number;
  quota: number | null | undefined;
  format?: (n: number) => string;
  compact?: boolean; // 表格里用：不显示标题
}) {
  const level = quotaLevel(used, quota);
  return (
    <div className="quota-meter">
      <div className="quota-meter-head">
        {!compact && <Typography.Text type="secondary">{label}</Typography.Text>}
        <span>
          <Typography.Text strong>{format(used)}</Typography.Text>
          <Typography.Text type="secondary"> / {quota == null ? "不限" : format(quota)}</Typography.Text>
        </span>
      </div>
      {level && (
        <>
          <Progress
            percent={Math.min(100, level.ratio * 100)}
            showInfo={false}
            strokeColor={level.stroke}
            railColor={level.rail}
            size={["100%", compact ? 6 : 8]}
          />
          {level.text && (
            <Typography.Text style={{ fontSize: 12 }}>
              {level.icon} {level.text}
            </Typography.Text>
          )}
        </>
      )}
    </div>
  );
}

/** 服务到期日：快到期（30 天内）、已到期的加标记 */
export function expiryTag(expiresAt: string | null | undefined) {
  if (!expiresAt) return <Typography.Text type="secondary">不限</Typography.Text>;
  const days = Math.ceil(dayjs(expiresAt).diff(dayjs(), "day", true)); // 剩 9.5 天算 10 天
  return (
    <Space size={4} wrap>
      {dayjs(expiresAt).format("YYYY-MM-DD")}
      {dayjs(expiresAt).isBefore(dayjs()) ? (
        <Tag color="red">已到期</Tag>
      ) : days < 30 ? (
        <Tag color="orange">{days} 天后到期</Tag>
      ) : null}
    </Space>
  );
}