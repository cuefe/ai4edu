import { Button, Result, Spin } from "antd";
import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router";
import { homePath, useAuth, type Role } from "./AuthProvider";

export function FullPageSpin() {
  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
      <Spin size="large" />
    </div>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <FullPageSpin />;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}

export function RequireRole({ roles }: { roles: Role[] }) {
  const { hasRole } = useAuth();
  const navigate = useNavigate();
  if (!hasRole(...roles)) {
    return (
      <Result
        status="403"
        title="没有权限"
        subTitle="当前账号不能访问这个页面"
        extra={<Button onClick={() => navigate("/")}>回到首页</Button>}
      />
    );
  }
  return <Outlet />;
}

export function HomeRedirect() {
  const { me } = useAuth();
  return <Navigate to={me ? homePath(me) : "/login"} replace />;
}
