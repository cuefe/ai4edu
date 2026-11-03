import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles, tenant_of
from app.core.errors import AppError, Forbidden
from app.core.routing import DbRoute
from app.modules.iam import service as iam
from app.modules.iam.models import Role, Tenant, User
from app.modules.iam.schemas import OkOut
from app.modules.ops import quota
from app.modules.ops import service as ops_service
from app.modules.ops.models import Plan
from app.modules.ops.service import audit
from app.modules.org import importer, service
from app.modules.org.models import MemberRole
from app.modules.org.schemas import (
    CampusIn,
    CampusOut,
    ClassIn,
    ClassOut,
    ClassPatch,
    ImportResultOut,
    MemberIn,
    MemberOut,
    OrgOverviewOut,
    ResetPasswordOut,
    SeatUsage,
    SkillUsage,
    StudentCreatedOut,
    StudentIn,
    TeacherIn,
    UserOut,
    UserPatch,
)

MAX_IMPORT_BYTES = 5 * 1024 * 1024

org_router = APIRouter(route_class=DbRoute, prefix="/org", tags=["机构管理"])
teacher_router = APIRouter(route_class=DbRoute, prefix="/teacher", tags=["教师"])
student_router = APIRouter(route_class=DbRoute, prefix="/student", tags=["学生"])

OrgAdmin = Depends(require_roles(Role.ORG_ADMIN))


# —— 机构管理员 ——


@org_router.get("/campuses", response_model=list[CampusOut])
def list_campuses(user: User = OrgAdmin, db: Session = Depends(get_db)):
    return [CampusOut(id=c.id, name=c.name) for c in service.list_campuses(db, tenant_of(user))]


@org_router.post("/campuses", response_model=CampusOut)
def create_campus(body: CampusIn, user: User = OrgAdmin, db: Session = Depends(get_db)):
    campus = service.create_campus(db, tenant_of(user), body)
    db.commit()
    return CampusOut(id=campus.id, name=campus.name)


@org_router.get("/classes", response_model=list[ClassOut])
def list_classes(user: User = OrgAdmin, db: Session = Depends(get_db)):
    return service.list_classes(db, tenant_of(user))


@org_router.post("/classes", response_model=ClassOut)
def create_class(body: ClassIn, user: User = OrgAdmin, db: Session = Depends(get_db)):
    klass = service.create_class(db, tenant_of(user), body)
    db.commit()
    return ClassOut(id=klass.id, name=klass.name, grade=klass.grade, campus_id=klass.campus_id)


@org_router.patch("/classes/{class_id}", response_model=ClassOut)
def update_class(class_id: uuid.UUID, body: ClassPatch, user: User = OrgAdmin, db: Session = Depends(get_db)):
    service.update_class(db, tenant_of(user), class_id, body)
    db.commit()
    return service.list_classes(db, tenant_of(user), [class_id])[0]


@org_router.get("/classes/{class_id}/members", response_model=list[MemberOut])
def list_members(class_id: uuid.UUID, user: User = OrgAdmin, db: Session = Depends(get_db)):
    return service.list_members(db, tenant_of(user), class_id)


@org_router.post("/classes/{class_id}/members", response_model=OkOut)
def add_member(class_id: uuid.UUID, body: MemberIn, user: User = OrgAdmin, db: Session = Depends(get_db)):
    service.add_member(db, tenant_of(user), class_id, body.user_id, body.member_role, body.subject)
    db.commit()
    return OkOut()


@org_router.delete("/classes/{class_id}/members/{user_id}", response_model=OkOut)
def remove_member(
    class_id: uuid.UUID, user_id: uuid.UUID, user: User = OrgAdmin, db: Session = Depends(get_db)
):
    service.remove_member(db, tenant_of(user), class_id, user_id)
    db.commit()
    return OkOut()


@org_router.get("/teachers", response_model=list[UserOut])
def list_teachers(q: str | None = None, user: User = OrgAdmin, db: Session = Depends(get_db)):
    return [service.to_user_out(u) for u in service.list_users(db, tenant_of(user), Role.TEACHER, q=q)]


@org_router.post("/teachers", response_model=UserOut)
def create_teacher(body: TeacherIn, user: User = OrgAdmin, db: Session = Depends(get_db)):
    teacher = service.create_teacher(db, tenant_of(user), body)
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="create_teacher",
        target_type="user",
        target_id=teacher.id,
        is_org_admin=body.is_org_admin,
    )
    db.commit()
    return service.to_user_out(teacher)


@org_router.get("/students", response_model=list[UserOut])
def list_students(
    class_id: uuid.UUID | None = None,
    q: str | None = None,
    user: User = OrgAdmin,
    db: Session = Depends(get_db),
):
    return [
        service.to_user_out(u)
        for u in service.list_users(db, tenant_of(user), Role.STUDENT, class_id=class_id, q=q)
    ]


@org_router.post("/students", response_model=StudentCreatedOut)
def create_student(body: StudentIn, user: User = OrgAdmin, db: Session = Depends(get_db)):
    student, generated = service.create_student(db, tenant_of(user), body)
    db.commit()
    return StudentCreatedOut(user=service.to_user_out(student), initial_password=generated)


@org_router.get("/students/import-template", summary="下载学生导入模板")
def import_template(_: User = OrgAdmin):
    return Response(
        content=importer.build_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('学生导入模板.xlsx')}"},
    )


@org_router.post("/students/import", response_model=ImportResultOut, summary="Excel 批量导入学生")
def import_students(file: UploadFile = File(...), user: User = OrgAdmin, db: Session = Depends(get_db)):
    content = file.file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise AppError("文件不能超过 5MB")
    result = importer.import_students(db, tenant_of(user), content)
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="import_students",
        created=result.created,
        skipped=result.skipped,
        errors=len(result.errors),
    )
    db.commit()
    return result


@org_router.get(
    "/overview", response_model=OrgOverviewOut, summary="机构概况：套餐、到期、名额、本月 AI 用量"
)
def overview(user: User = OrgAdmin, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    plan = db.get(Plan, tenant.plan_id) if tenant.plan_id else None
    since = quota.month_start()
    return OrgOverviewOut(
        name=tenant.name,
        code=tenant.code,
        plan_name=plan.name if plan else None,
        expires_at=tenant.expires_at,
        students=SeatUsage(used=quota.seats_used(db, tenant_id, Role.STUDENT), quota=tenant.student_quota),
        teachers=SeatUsage(used=quota.seats_used(db, tenant_id, Role.TEACHER), quota=tenant.teacher_quota),
        ai_spend_yuan=quota.month_spend(db, tenant_id),
        ai_budget_yuan=tenant.ai_budget_yuan,
        ai_by_skill=[
            SkillUsage(skill=skill, calls=calls, cost_yuan=cost)
            for skill, calls, cost in ops_service.usage_by_skill(db, tenant_id, since)
        ],
    )


@org_router.patch("/users/{user_id}", response_model=UserOut, summary="停用或启用账号")
def update_user(user_id: uuid.UUID, body: UserPatch, user: User = OrgAdmin, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    target = service.get_user(db, tenant_id, user_id)
    was_active = target.active
    service.set_active(db, tenant_id, user, target, body.active)
    if target.active != was_active:
        audit(
            db,
            tenant_id=tenant_id,
            actor_id=user.id,
            action="enable_user" if target.active else "disable_user",
            target_type="user",
            target_id=target.id,
        )
    db.commit()
    return service.to_user_out(target)


@org_router.post("/users/{user_id}/reset-password", response_model=ResetPasswordOut)
def reset_password(user_id: uuid.UUID, user: User = OrgAdmin, db: Session = Depends(get_db)):
    target = service.get_user(db, tenant_of(user), user_id)
    if target.has_role(Role.ORG_ADMIN) and target.id != user.id:
        raise Forbidden("不能重置其他管理员的密码")
    password = iam.reset_password(target)
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="reset_password",
        target_type="user",
        target_id=target.id,
    )
    db.commit()
    return ResetPasswordOut(password=password)


# —— 老师 ——


@teacher_router.get("/classes", response_model=list[ClassOut], summary="我任教的班级")
def my_teaching_classes(user: User = Depends(require_roles(Role.TEACHER)), db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    return service.list_classes(
        db, tenant_id, service.class_ids_of(db, tenant_id, user.id, MemberRole.TEACHER)
    )


@teacher_router.get("/classes/{class_id}/students", response_model=list[MemberOut])
def class_students(
    class_id: uuid.UUID, user: User = Depends(require_roles(Role.TEACHER)), db: Session = Depends(get_db)
):
    tenant_id = tenant_of(user)
    if class_id not in service.class_ids_of(db, tenant_id, user.id, MemberRole.TEACHER):
        raise Forbidden("你不是这个班的老师")
    return service.list_members(db, tenant_id, class_id, MemberRole.STUDENT)


# —— 学生 ——


@student_router.get("/classes", response_model=list[ClassOut], summary="我所在的班级")
def my_classes(user: User = Depends(require_roles(Role.STUDENT)), db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    return service.list_classes(
        db, tenant_id, service.class_ids_of(db, tenant_id, user.id, MemberRole.STUDENT)
    )
