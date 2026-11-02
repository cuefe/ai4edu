import type { Schemas } from "@/api/client";

export type LessonPlanIn = Schemas["LessonPlanIn"];

export const SUBJECTS: LessonPlanIn["subject"][] = ["数学", "英语"];
export const GRADES: LessonPlanIn["grade"][] = ["七年级上册", "七年级下册", "八年级上册", "八年级下册", "九年级上册", "九年级下册"];
export const LESSON_TYPES: NonNullable<LessonPlanIn["lesson_type"]>[] = ["新授课", "复习课", "习题课", "讲评课"];
export const TEXTBOOKS = ["人教版", "北师大版", "华东师大版", "苏科版", "湘教版", "外研版", "译林版"];

export const STATUS_TAG: Record<string, { color: string; label: string } | undefined> = {
  generating: { color: "processing", label: "生成中" },
  failed: { color: "error", label: "生成失败" },
};
