import uuid
from datetime import date

from pydantic import BaseModel, Field


class ProgressIn(BaseModel):
    book_id: uuid.UUID
    section_ids: list[uuid.UUID] = Field(min_length=1, max_length=50, description="这周教的节")
    enabled: bool = Field(default=True, description="关掉后不再发周测")


class SectionOut(BaseModel):
    id: uuid.UUID
    no: str
    title: str
    chapter_no: str
    chapter_title: str
    approved_count: int = Field(description="这一节审核通过、可以进卷的题数")


class ProgressOut(BaseModel):
    subject: str
    book_id: uuid.UUID
    book_title: str
    section_ids: list[uuid.UUID]
    section_labels: list[str]
    enabled: bool
    week_start: date
    up_to_date: bool = Field(description="这周更新过进度")


class WeekStat(BaseModel):
    week_start: date
    issued: int = Field(description="这周发了几份")
    submitted: int
    graded: int
    pending_review: int = Field(description="等老师确认的题数")
    avg_percent: float | None = Field(description="已提交的平均得分率，百分制")


class ClassWeeklyOut(BaseModel):
    klass_id: uuid.UUID
    class_name: str
    grade: str | None
    subject: str | None = Field(description="老师在这个班教的学科；没有填时由所选教材决定")
    student_count: int
    progress: ProgressOut | None
    week: WeekStat | None


class IssueResult(BaseModel):
    week_start: date
    created: int = Field(description="这次发了几份")
    existing: int = Field(description="这周已经发过的份数，不会重复发")
    short: list[str] = Field(description="题库不够、这次没发成的学生")
    partial: list[str] = Field(description="题库不够、卷子题目偏少的学生")
    stale_progress: bool = Field(description="进度这周没更新，用的是上次设置的节")


class KpMastery(BaseModel):
    kp_id: uuid.UUID
    name: str
    section_no: str
    mastery: float = Field(description="掌握度，0～1")


class StudentWeekRow(BaseModel):
    student_id: uuid.UUID
    student_name: str
    username: str | None
    assignment_id: uuid.UUID | None = Field(description="这周没发卷时为空")
    level: int | None
    level_label: str | None
    reason: str
    status: str | None = Field(description="todo 未提交 / submitted 待批改 / graded 已批改")
    score: float | None
    total_score: float | None
    percent: float | None = Field(description="得分率，百分制；含 AI 给的还没确认的分")
    pending_count: int
    prev_percent: float | None
    weak_kps: list[KpMastery] = Field(description="掌握度最低的几个知识点")


class ClassWeekReport(BaseModel):
    klass_id: uuid.UUID
    class_name: str
    subject: str
    week_start: date
    weeks: list[date] = Field(description="有周测的周，新的在前")
    rows: list[StudentWeekRow]
    class_weak_kps: list[KpMastery] = Field(description="全班平均掌握度最低的知识点")


class WeekRow(BaseModel):
    week_start: date
    assignment_id: uuid.UUID
    title: str
    status: str
    score: float | None
    total_score: float
    percent: float | None = Field(description="得分率，百分制；只算已经出分的题")
    level: int
    level_label: str
    reason: str
    origins: dict[str, int] = Field(description="各来源的题数：this_week / weak / wrong / review")


class SubjectWeekly(BaseModel):
    subject: str
    book_title: str
    level: int
    level_label: str
    weeks: list[WeekRow] = Field(description="新的在前")
    weak_kps: list[KpMastery]
    tested_kps: int = Field(description="考过的知识点数")
    mastered_kps: int = Field(description="掌握度达到 0.8 的知识点数")
