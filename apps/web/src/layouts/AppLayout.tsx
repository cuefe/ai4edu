import {
  AlertOutlined,
  ApartmentOutlined,
  BookOutlined,
  CloudServerOutlined,
  CreditCardOutlined,
  DownOutlined,
  EditOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  HomeOutlined,
  LogoutOutlined,
  MenuOutlined,
  MessageOutlined,
  ReadOutlined,
  RobotOutlined,
  SnippetsOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Drawer, Dropdown, Grid, Layout, Menu, Space, Typography, type MenuProps } from "antd";
import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import { useAuth } from "@/auth/AuthProvider";
import { ChangePasswordModal } from "@/components/ChangePasswordModal";
import { NotificationBell } from "@/components/NotificationBell";

type MenuItem = Required<MenuProps>["items"][number];

export function AppLayout() {
  const { me, hasRole, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const screens = Grid.useBreakpoint();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pwdOpen, setPwdOpen] = useState(false);

  const items: MenuItem[] = [];
  if (hasRole("platform_admin")) {
    items.push({
      type: "group",
      label: "平台运营",
      children: [
        { key: "/ops/tenants", icon: <CloudServerOutlined />, label: "机构管理" },
        { key: "/ops/ai", icon: <RobotOutlined />, label: "AI 模型" },
      ],
    });
  }
  const alerts = { key: "/alerts", icon: <AlertOutlined />, label: "心理预警" };
  if (hasRole("org_admin")) {
    items.push({
      type: "group",
      label: "机构管理",
      children: [
        { key: "/org/classes", icon: <ApartmentOutlined />, label: "班级" },
        { key: "/org/teachers", icon: <UserOutlined />, label: "老师" },
        { key: "/org/students", icon: <TeamOutlined />, label: "学生" },
        ...(hasRole("teacher") ? [] : [alerts]), // 兼任老师的放在“教学”里，菜单里只出现一次
      ],
    });
  }
  if (hasRole("teacher")) {
    items.push(
      {
        type: "group",
        label: "教学",
        children: [
          { key: "/teacher", icon: <HomeOutlined />, label: "我的班级" },
          { key: "/teacher/assignments", icon: <SnippetsOutlined />, label: "作业" },
          alerts,
        ],
      },
      {
        type: "group",
        label: "备课",
        children: [
          { key: "/teacher/lesson-plans", icon: <EditOutlined />, label: "教案" },
          { key: "/teacher/handouts", icon: <FileTextOutlined />, label: "讲义" },
          { key: "/teacher/recite", icon: <CreditCardOutlined />, label: "背诵卡片" },
          { key: "/teacher/questions", icon: <BookOutlined />, label: "题库" },
          { key: "/teacher/resources", icon: <FolderOpenOutlined />, label: "资料库" },
        ],
      },
    );
  }
  if (hasRole("student")) {
    items.push({
      type: "group",
      label: "学习",
      children: [
        { key: "/student", icon: <ReadOutlined />, label: "首页" },
        { key: "/student/assignments", icon: <SnippetsOutlined />, label: "作业" },
        { key: "/student/review", icon: <CreditCardOutlined />, label: "背诵" },
        { key: "/student/wrong", icon: <BookOutlined />, label: "错题本" },
        { key: "/student/tutor", icon: <MessageOutlined />, label: "问一问" },
      ],
    });
  }

  const userMenu: MenuProps["items"] = [
    { key: "password", label: "修改密码", onClick: () => setPwdOpen(true) },
    { type: "divider" },
    { key: "logout", icon: <LogoutOutlined />, label: "退出登录", danger: true, onClick: logout },
  ];

  // 断点未测出前 md 为 undefined，按桌面处理，避免闪一下手机布局
  const isMobile = screens.md === false;

  // 子页面（如 /teacher/lesson-plans/新建）高亮所属菜单：取路径前缀最长的那一项
  const menuKeys = items.flatMap((g) => (g && "children" in g && g.children ? g.children : [])).map((i) => String(i?.key));
  const selectedKey = menuKeys
    .filter((k) => location.pathname === k || location.pathname.startsWith(`${k}/`))
    .sort((a, b) => b.length - a.length)[0];

  const menu = (
    <Menu
      mode="inline"
      selectedKeys={selectedKey ? [selectedKey] : []}
      items={items}
      onClick={({ key }) => {
        navigate(key);
        setDrawerOpen(false);
      }}
      style={{ borderInlineEnd: 0 }}
    />
  );

  return (
    <Layout style={{ minHeight: "100vh" }}>
      {isMobile ? (
        <Drawer
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          title="AI 智教平台"
          size={240}
          styles={{ body: { padding: 0 } }}
        >
          {menu}
        </Drawer>
      ) : (
        <Layout.Sider
          theme="light"
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          collapsedWidth={64}
          width={208}
          style={{ borderInlineEnd: "1px solid #eef0f5" }}
        >
          <div style={{ height: 56, display: "flex", alignItems: "center", paddingInline: 20 }}>
            <Typography.Text strong style={{ fontSize: 16, whiteSpace: "nowrap" }}>
              {collapsed ? "智教" : "AI 智教平台"}
            </Typography.Text>
          </div>
          {menu}
        </Layout.Sider>
      )}
      <Layout>
        <Layout.Header
          style={{
            background: "#fff",
            paddingInline: 16,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            borderBottom: "1px solid #eef0f5",
          }}
        >
          {isMobile ? (
            <Button type="text" icon={<MenuOutlined />} onClick={() => setDrawerOpen(true)} aria-label="打开菜单" />
          ) : (
            <span />
          )}
          <Space size="middle">
            {me?.tenant && !isMobile && <Typography.Text type="secondary">{me.tenant.name}</Typography.Text>}
            {me?.tenant && <NotificationBell />}
            <Dropdown menu={{ items: userMenu }} trigger={["click"]}>
              <a onClick={(e) => e.preventDefault()} style={{ color: "inherit" }}>
                <Space size={6}>
                  <Avatar size="small" icon={<UserOutlined />} />
                  {me?.name}
                  <DownOutlined style={{ fontSize: 10 }} />
                </Space>
              </a>
            </Dropdown>
          </Space>
        </Layout.Header>
        <Layout.Content style={{ padding: isMobile ? 16 : 24 }}>
          <Outlet />
        </Layout.Content>
      </Layout>
      <ChangePasswordModal
        open={pwdOpen || Boolean(me?.must_change_password)}
        forced={Boolean(me?.must_change_password)}
        onClose={() => setPwdOpen(false)}
      />
    </Layout>
  );
}
