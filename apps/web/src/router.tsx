import { Button, Result } from "antd";
import { createBrowserRouter, Outlet, useNavigate } from "react-router";
import { AuthProvider } from "./auth/AuthProvider";
import { HomeRedirect, RequireAuth, RequireRole } from "./auth/guards";
import { AppLayout } from "./layouts/AppLayout";
import { LoginPage } from "./pages/LoginPage";
import { AiPage } from "./pages/ops/AiPage";
import { TenantsPage } from "./pages/ops/TenantsPage";
import { ClassesPage } from "./pages/org/ClassesPage";
import { StudentsPage } from "./pages/org/StudentsPage";
import { TeachersPage } from "./pages/org/TeachersPage";
import { StudentHome } from "./pages/student/StudentHome";
import { TeacherHome } from "./pages/teacher/TeacherHome";

function Root() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  );
}

function NotFound() {
  const navigate = useNavigate();
  return (
    <Result
      status="404"
      title="页面不存在"
      extra={<Button onClick={() => navigate("/")}>回到首页</Button>}
    />
  );
}

export const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      { path: "/login", element: <LoginPage /> },
      {
        element: (
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        ),
        children: [
          { index: true, element: <HomeRedirect /> },
          {
            path: "ops",
            element: <RequireRole roles={["platform_admin"]} />,
            children: [
              { path: "tenants", element: <TenantsPage /> },
              { path: "ai", element: <AiPage /> },
            ],
          },
          {
            path: "org",
            element: <RequireRole roles={["org_admin"]} />,
            children: [
              { path: "classes", element: <ClassesPage /> },
              { path: "teachers", element: <TeachersPage /> },
              { path: "students", element: <StudentsPage /> },
            ],
          },
          {
            path: "teacher",
            element: <RequireRole roles={["teacher"]} />,
            children: [{ index: true, element: <TeacherHome /> }],
          },
          {
            path: "student",
            element: <RequireRole roles={["student"]} />,
            children: [{ index: true, element: <StudentHome /> }],
          },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);
