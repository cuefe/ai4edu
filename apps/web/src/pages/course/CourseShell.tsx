import type { ReactNode } from "react";
import { StudentPage } from "@/pages/student/StudentHome";

/** 学生端用大号控件；老师和运营用默认样式。 */
export function CourseShell({ base, children }: { base: string; children: ReactNode }) {
  return base.startsWith("/student") ? <StudentPage>{children}</StudentPage> : <>{children}</>;
}
