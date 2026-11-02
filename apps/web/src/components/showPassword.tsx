import { App, Typography } from "antd";

type ModalApi = ReturnType<typeof App.useApp>["modal"];

/** 弹窗展示新密码。密码只显示这一次，提醒管理员转告。 */
export function showPassword(modal: ModalApi, title: string, name: string, password: string) {
  modal.success({
    title,
    content: (
      <>
        <Typography.Paragraph>
          {name} 的新密码是：
          <Typography.Text strong copyable code style={{ fontSize: 16 }}>
            {password}
          </Typography.Text>
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary">
          密码只显示这一次，请转告本人。对方首次登录后需要修改密码。
        </Typography.Paragraph>
      </>
    ),
  });
}
