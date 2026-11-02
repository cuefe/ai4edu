import { Typography } from "antd";
import type { ReactNode } from "react";

export function PageHead({ title, extra }: { title: ReactNode; extra?: ReactNode }) {
  return (
    <div className="page-head">
      <Typography.Title level={4}>{title}</Typography.Title>
      {extra}
    </div>
  );
}
