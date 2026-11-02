import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.ai.skills.common import Grade, Subject
from app.ai.skills.question_gen import Difficulty, QuestionData, QuestionGenIn


class QuestionIn(QuestionData):
    """老师手动录题或修改题目。"""

    subject: Subject
    grade: Grade | None = None
    difficulty: Difficulty = "中等"


class CheckOut(BaseModel):
    verdict: str = Field(description="agree 一致 / disagree 不一致 / unsure 判断不了 / error 校验失败")
    method: str = Field(description="rule 规则比对 / numeric 数值比对 / judge 模型比对")
    solver_model: str | None
    solver_answer: str | None
    solver_work: str
    reason: str
    created_at: datetime


class QuestionOut(BaseModel):
    id: uuid.UUID
    subject: str
    grade: str | None
    qtype: str
    difficulty: str
    stem: str
    options: list[str]
    answer: str
    analysis: str
    knowledge_points: list[str]
    source: str = Field(description="ai / manual")
    status: str = Field(
        description="checking 校验中 / checked、disputed、unchecked 待审核 / approved 已入库 / rejected 驳回"
    )
    edited: bool = Field(description="AI 出的题老师改过")
    warnings: list[str]
    batch_id: uuid.UUID | None
    owner_name: str
    mine: bool
    check: CheckOut | None = Field(description="最近一次答案校验")
    created_at: datetime
    updated_at: datetime


class QuestionPage(BaseModel):
    items: list[QuestionOut]
    total: int


class QuestionCounts(BaseModel):
    review: int = Field(description="我的待审核")
    bank: int = Field(description="机构题库（已入库）")
    rejected: int = Field(description="我驳回的")


class BatchOut(BaseModel):
    id: uuid.UUID
    topic: str
    params: QuestionGenIn | None = Field(description="出题参数，“再出一批”时回填表单")
    status: str = Field(description="generating 出题中 / checking 校验中 / done / failed")
    progress: int
    error: str | None
    warnings: list[str]
    sources: list[dict]
    created_at: datetime
    questions: list[QuestionOut]


QuestionView = Literal["review", "bank", "rejected"]
