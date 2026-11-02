import { Button, Result, Spin } from "antd";
import { lazy, Suspense, type ReactNode } from "react";
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
import { LessonPlansPage } from "./pages/teacher/LessonPlansPage";
import { ResourcesPage } from "./pages/teacher/ResourcesPage";
import { TeacherHome } from "./pages/teacher/TeacherHome";

// 编辑器、公式、Markdown 渲染体积较大，只在打开这些页面时加载
const LessonPlanNewPage = lazy(() =>
  import("./pages/teacher/LessonPlanNewPage").then((m) => ({ default: m.LessonPlanNewPage })),
);
const LessonPlanEditPage = lazy(() =>
  import("./pages/teacher/LessonPlanEditPage").then((m) => ({ default: m.LessonPlanEditPage })),
);

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<Spin style={{ display: "block", marginTop: 96 }} />}>{children}</Suspense>;
}

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
            children: [
              { index: true, element: <TeacherHome /> },
              { path: "lesson-plans", element: <LessonPlansPage /> },
              { path: "resources", element: <ResourcesPage /> },
              {
                path: "lesson-plans/new",
                element: (
                  <Lazy>
                    <LessonPlanNewPage />
                  </Lazy>
                ),
              },
              {
                path: "lesson-plans/:id",
                element: (
                  <Lazy>
                    <LessonPlanEditPage />
                  </Lazy>
                ),
              },
            ],
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
