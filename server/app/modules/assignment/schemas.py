import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.ai.skills.common import Subject
from app.modules.assignment.models import AnswerRelease, ItemType


class ItemIn(BaseModel):
    item_type: ItemType
    ref_id: uuid.UUID = Field(description="题目、讲义或卡片组的 ID")
    score: float = Field(default=0, ge=0, le=100, description="题目分值，0 表示用默认分值；阅读、背诵不计分")


class AssignmentIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    subject: Subject
    note: str = Field(default="", max_length=1000, description="给学生的要求")
    class_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    student_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=200, description="另外单独布置给的学生"
    )
    publish_at: datetime | None = Field(default=None, description="为空表示马上发布")
    due_at: datetime | None = None
    answer_release: AnswerRelease = AnswerRelease.SUBMIT
    allow_ai: bool = Field(default=True, description="作业期间允许问 AI（只给提示，不给答案）")
    items: list[ItemIn] = Field(min_length=1, max_length=50)


class ItemOut(BaseModel):
    id: uuid.UUID
    seq: int
    item_type: str
    score: float
    content: dict[str, Any] = Field(description="快照；学生端在答案公布前不含 answer、analysis")


class AssignmentBrief(BaseModel):
    id: uuid.UUID
    title: str
    subject: str
    class_names: list[str]
    publish_at: datetime
    due_at: datetime | None
    answer_release: str
    allow_ai: bool
    total_score: float
    student_count: int
    submitted_count: int
    pending_review: int = Field(description="等老师确认的题数")
    avg_score: float | None
    created_at: datetime


class ItemStat(BaseModel):
    item_id: uuid.UUID
    seq: int
    answered: int
    correct: int
    avg_score: float | None
    accuracy: float | None = Field(description="得满分的比例")
    common_wrong: bool = Field(description="共性错题：错误率达到阈值")


class SubmissionRow(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    username: str | None
    class_name: str | None
    status: str
    submitted_at: datetime | None
    late: bool
    score: float | None
    pending_count: int
    progress_done: int = Field(description="完成的阅读、背诵项数")


class AssignmentReport(AssignmentBrief):
    note: str
    items: list[ItemOut]
    graded_count: int
    item_stats: list[ItemStat]
    submissions: list[SubmissionRow]


class AnswerOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    response: str
    image_count: int
    status: str
    correct: bool | None
    score: float | None
    ai_score: float | None
    ai_confidence: float | None
    ai_comment: str
    ai_points: list[str]
    teacher_comment: str


class GradingRow(AnswerOut):
    student_name: str
    item_seq: int
    item_score: float
    question: dict[str, Any]


class ConfirmIn(BaseModel):
    score: float | None = Field(default=None, ge=0, description="为空表示采用 AI 给的分")
    comment: str | None = Field(default=None, max_length=1000)


class SubmissionDetail(BaseModel):
    """老师查看某个学生的作答。"""

    submission: SubmissionRow
    answers: list[AnswerOut]


# —— 学生端 ——


class StudentAssignmentBrief(BaseModel):
    id: uuid.UUID
    title: str
    subject: str
    teacher_name: str
    publish_at: datetime
    due_at: datetime | None
    status: str
    score: float | None
    total_score: float
    question_count: int
    task_count: int = Field(description="阅读、背诵项数")
    progress_done: int


class StudentAssignment(StudentAssignmentBrief):
    note: str
    allow_ai: bool
    revealed: bool = Field(description="答案和解析是否已公布")
    submitted_at: datetime | None
    pending_count: int
    items: list[ItemOut]
    answers: list[AnswerOut]
    recite_progress: dict[str, int] = Field(description="背诵项学过的卡片数：{item_id: 张数}")
    progress: dict[str, bool] = Field(description="阅读、背诵项是否完成：{item_id: true}")


class ResponseIn(BaseModel):
    response: str = Field(max_length=5000)
