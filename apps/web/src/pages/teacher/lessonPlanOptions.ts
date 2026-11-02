import type { Schemas } from "@/api/client";

export type LessonPlanIn = Schemas["LessonPlanIn"];
export type HandoutIn = Schemas["HandoutIn"];

export const SUBJECTS: LessonPlanIn["subject"][] = ["数学", "英语"];
export const GRADES: LessonPlanIn["grade"][] = ["七年级上册", "七年级下册", "八年级上册", "八年级下册", "九年级上册", "九年级下册"];
export const LESSON_TYPES: NonNullable<LessonPlanIn["lesson_type"]>[] = ["新授课", "复习课", "习题课", "讲评课"];
export const HANDOUT_KINDS: NonNullable<HandoutIn["kind"]>[] = ["课堂讲义", "复习讲义"];
export const TEXTBOOKS = ["人教版", "北师大版", "华东师大版", "苏科版", "湘教版", "外研版", "译林版"];

export const STATUS_TAG: Record<string, { color: string; label: string } | undefined> = {
  generating: { color: "processing", label: "生成中" },
  failed: { color: "error", label: "生成失败" },
};

/** 可以 AI 生成的文档类型：列表、编辑页按类型取标题和路径。 */
export const DOC_TYPES = {
  lesson_plan: { label: "教案", base: "/teacher/lesson-plans", generatePath: "/api/teacher/lesson-plans/generate" },
  handout: { label: "讲义", base: "/teacher/handouts", generatePath: "/api/teacher/handouts/generate" },
} as const;

export type DocType = keyof typeof DOC_TYPES;

export function docTypeOf(value: string): DocType {
  return value in DOC_TYPES ? (value as DocType) : "lesson_plan";
}
