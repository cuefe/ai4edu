import { Button, Result, Spin } from "antd";
import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Outlet, useNavigate } from "react-router";
import { AuthProvider } from "./auth/AuthProvider";
import { HomeRedirect, RequireAuth, RequireRole } from "./auth/guards";
import { AppLayout } from "./layouts/AppLayout";
import { LoginPage } from "./pages/LoginPage";
import { AiPage } from "./pages/ops/AiPage";
import { AuditPage } from "./pages/ops/AuditPage";
import { PlansPage } from "./pages/ops/PlansPage";
import { SafetyPage } from "./pages/ops/SafetyPage";
import { TenantsPage } from "./pages/ops/TenantsPage";
import { UsagePage } from "./pages/ops/UsagePage";
import { ClassesPage } from "./pages/org/ClassesPage";
import { OverviewPage } from "./pages/org/OverviewPage";
import { StudentsPage } from "./pages/org/StudentsPage";
import { TeachersPage } from "./pages/org/TeachersPage";
import { StudentAssignmentsPage } from "./pages/student/StudentAssignmentsPage";
import { StudentHome } from "./pages/student/StudentHome";
import { AssignmentsPage } from "./pages/teacher/AssignmentsPage";
import { DocumentsPage } from "./pages/teacher/DocumentsPage";
import { RecitePage } from "./pages/teacher/RecitePage";
import { ResourcesPage } from "./pages/teacher/ResourcesPage";
import { TeacherHome } from "./pages/teacher/TeacherHome";

// 编辑器、公式、Markdown 渲染体积较大，只在打开这些页面时加载
const LessonPlanNewPage = lazy(() =>
  import("./pages/teacher/LessonPlanNewPage").then((m) => ({ default: m.LessonPlanNewPage })),
);
const HandoutNewPage = lazy(() => import("./pages/teacher/HandoutNewPage").then((m) => ({ default: m.HandoutNewPage })));
const DocumentEditPage = lazy(() =>
  import("./pages/teacher/DocumentEditPage").then((m) => ({ default: m.DocumentEditPage })),
);
const ReciteDeckPage = lazy(() => import("./pages/teacher/ReciteDeckPage").then((m) => ({ default: m.ReciteDeckPage })));
const QuestionsPage = lazy(() => import("./pages/teacher/QuestionsPage").then((m) => ({ default: m.QuestionsPage })));
const QuestionGenPage = lazy(() => import("./pages/teacher/QuestionGenPage").then((m) => ({ default: m.QuestionGenPage })));
const AssignmentNewPage = lazy(() =>
  import("./pages/teacher/AssignmentNewPage").then((m) => ({ default: m.AssignmentNewPage })),
);
const AssignmentReportPage = lazy(() =>
  import("./pages/teacher/AssignmentReportPage").then((m) => ({ default: m.AssignmentReportPage })),
);
const AlertsPage = lazy(() => import("./pages/AlertsPage").then((m) => ({ default: m.AlertsPage })));
const StudentAssignmentPage = lazy(() =>
  import("./pages/student/StudentAssignmentPage").then((m) => ({ default: m.StudentAssignmentPage })),
);
const ReviewPage = lazy(() => import("./pages/student/ReviewPage").then((m) => ({ default: m.ReviewPage })));
const WrongBookPage = lazy(() => import("./pages/student/WrongBookPage").then((m) => ({ default: m.WrongBookPage })));
const WrongItemPage = lazy(() => import("./pages/student/WrongBookPage").then((m) => ({ default: m.WrongItemPage })));
const TutorPage = lazy(() => import("./pages/student/TutorPage").then((m) => ({ default: m.TutorPage })));

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<Spin style={{ display: "block", marginTop: 96 }} />}>{children}</Suspense>;
}

const lazyRoute = (path: string, element: ReactNode) => ({ path, element: <Lazy>{element}</Lazy> });

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
              { path: "plans", element: <PlansPage /> },
              { path: "usage", element: <UsagePage /> },
              { path: "ai", element: <AiPage /> },
              { path: "safety", element: <SafetyPage /> },
              { path: "audit", element: <AuditPage /> },
            ],
          },
          {
            path: "org",
            element: <RequireRole roles={["org_admin"]} />,
            children: [
              { path: "overview", element: <OverviewPage /> },
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
              { path: "lesson-plans", element: <DocumentsPage key="lesson_plan" docType="lesson_plan" /> },
              lazyRoute("lesson-plans/new", <LessonPlanNewPage />),
              lazyRoute("lesson-plans/:id", <DocumentEditPage docType="lesson_plan" />),
              { path: "handouts", element: <DocumentsPage key="handout" docType="handout" /> },
              lazyRoute("handouts/new", <HandoutNewPage />),
              lazyRoute("handouts/:id", <DocumentEditPage docType="handout" />),
              { path: "recite", element: <RecitePage /> },
              lazyRoute("recite/:id", <ReciteDeckPage />),
              lazyRoute("questions", <QuestionsPage />),
              lazyRoute("questions/new", <QuestionGenPage />),
              { path: "resources", element: <ResourcesPage /> },
              { path: "assignments", element: <AssignmentsPage /> },
              lazyRoute("assignments/new", <AssignmentNewPage />),
              lazyRoute("assignments/:id", <AssignmentReportPage />),
            ],
          },
          {
            path: "alerts",
            element: <RequireRole roles={["teacher", "org_admin"]} />,
            children: [lazyRoute("", <AlertsPage />)],
          },
          {
            path: "student",
            element: <RequireRole roles={["student"]} />,
            children: [
              { index: true, element: <StudentHome /> },
              { path: "assignments", element: <StudentAssignmentsPage /> },
              lazyRoute("assignments/:id", <StudentAssignmentPage />),
              lazyRoute("review", <ReviewPage />),
              lazyRoute("wrong", <WrongBookPage />),
              lazyRoute("wrong/:id", <WrongItemPage />),
              lazyRoute("tutor", <TutorPage />),
              lazyRoute("tutor/:sid", <TutorPage />),
            ],
          },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);
