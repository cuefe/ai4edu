import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.org.models import MemberRole


class CampusIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CampusOut(BaseModel):
    id: uuid.UUID
    name: str


class ClassIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    grade: str | None = Field(default=None, max_length=20)
    campus_id: uuid.UUID | None = None


class ClassPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    grade: str | None = Field(default=None, max_length=20)
    campus_id: uuid.UUID | None = None


class ClassOut(BaseModel):
    id: uuid.UUID
    name: str
    grade: str | None
    campus_id: uuid.UUID | None
    teacher_count: int = 0
    student_count: int = 0


class UserOut(BaseModel):
    id: uuid.UUID
    name: str
    roles: list[str]
    username: str | None = None
    phone_masked: str | None = None
    active: bool


class TeacherIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=11, max_length=20)
    password: str | None = Field(default=None, min_length=6, max_length=64)  # 不填则只能用验证码登录
    is_org_admin: bool = False


class StudentIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_\-]+$")
    class_id: uuid.UUID | None = None
    password: str | None = Field(default=None, min_length=6, max_length=64)  # 不填则自动生成


class StudentCreatedOut(BaseModel):
    user: UserOut
    initial_password: str | None = None


class MemberIn(BaseModel):
    user_id: uuid.UUID
    member_role: MemberRole
    subject: str | None = Field(default=None, max_length=20)


class MemberOut(BaseModel):
    user: UserOut
    member_role: str
    subject: str | None


class RowError(BaseModel):
    row: int
    message: str


class Credential(BaseModel):
    name: str
    username: str
    class_name: str | None
    password: str


class ImportResultOut(BaseModel):
    created: int
    skipped: int
    errors: list[RowError]
    credentials: list[Credential]  # 只在这一次返回，前端提示管理员下载保存


class ResetPasswordOut(BaseModel):
    password: str


class UserPatch(BaseModel):
    active: bool


class SeatUsage(BaseModel):
    used: int
    quota: int | None = Field(description="为空表示不限")


class SkillUsage(BaseModel):
    skill: str
    calls: int
    cost_yuan: Decimal


class OrgOverviewOut(BaseModel):
    name: str
    code: str
    plan_name: str | None
    expires_at: datetime | None
    students: SeatUsage
    teachers: SeatUsage
    ai_spend_yuan: Decimal = Field(description="本月 AI 费用（北京时间自然月）")
    ai_budget_yuan: Decimal | None = Field(description="每月 AI 费用上限，为空表示不限")
    ai_by_skill: list[SkillUsage] = Field(description="本月各功能的调用次数和费用")
