"""机构内的校区、班级、师生管理。所有函数都显式带 tenant_id 过滤（数据库层另有行级安全兜底）。"""

import uuid

from sqlalchemy import any_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Forbidden, NotFound
from app.core.security import generate_password
from app.modules.iam import service as iam
from app.modules.iam import sms
from app.modules.iam.models import Role, User
from app.modules.ops import quota
from app.modules.org.models import Campus, ClassMember, Klass, MemberRole
from app.modules.org.schemas import (
    CampusIn,
    ClassIn,
    ClassOut,
    ClassPatch,
    MemberOut,
    StudentIn,
    TeacherIn,
    UserOut,
)


def to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        roles=user.roles,
        username=user.username,
        phone_masked=iam.user_phone_masked(user),
        active=user.active,
    )


# —— 校区 ——


def list_campuses(db: Session, tenant_id: uuid.UUID) -> list[Campus]:
    return list(db.scalars(select(Campus).where(Campus.tenant_id == tenant_id).order_by(Campus.created_at)))


def create_campus(db: Session, tenant_id: uuid.UUID, body: CampusIn) -> Campus:
    campus = Campus(tenant_id=tenant_id, name=body.name.strip())
    db.add(campus)
    db.flush()
    return campus


# —— 班级 ——


def get_class(db: Session, tenant_id: uuid.UUID, class_id: uuid.UUID) -> Klass:
    klass = db.scalar(select(Klass).where(Klass.id == class_id, Klass.tenant_id == tenant_id))
    if klass is None:
        raise NotFound("班级不存在")
    return klass


def list_classes(
    db: Session, tenant_id: uuid.UUID, class_ids: list[uuid.UUID] | None = None
) -> list[ClassOut]:
    counts = (
        select(
            ClassMember.klass_id,
            func.count(case((ClassMember.member_role == MemberRole.TEACHER, 1))).label("teachers"),
            func.count(case((ClassMember.member_role == MemberRole.STUDENT, 1))).label("students"),
        )
        .where(ClassMember.tenant_id == tenant_id)
        .group_by(ClassMember.klass_id)
        .subquery()
    )
    stmt = (
        select(Klass, counts.c.teachers, counts.c.students)
        .outerjoin(counts, counts.c.klass_id == Klass.id)
        .where(Klass.tenant_id == tenant_id)
        .order_by(Klass.grade, Klass.name)
    )
    if class_ids is not None:
        stmt = stmt.where(Klass.id.in_(class_ids))
    return [
        ClassOut(
            id=k.id,
            name=k.name,
            grade=k.grade,
            campus_id=k.campus_id,
            teacher_count=teachers or 0,
            student_count=students or 0,
        )
        for k, teachers, students in db.execute(stmt)
    ]


def _check_campus(db: Session, tenant_id: uuid.UUID, campus_id: uuid.UUID | None) -> None:
    if campus_id and not db.scalar(
        select(Campus.id).where(Campus.id == campus_id, Campus.tenant_id == tenant_id)
    ):
        raise NotFound("校区不存在")


def create_class(db: Session, tenant_id: uuid.UUID, body: ClassIn) -> Klass:
    _check_campus(db, tenant_id, body.campus_id)
    if db.scalar(select(Klass.id).where(Klass.tenant_id == tenant_id, Klass.name == body.name.strip())):
        raise AppError(f"班级 {body.name} 已存在", code="class_exists", status=409)
    klass = Klass(tenant_id=tenant_id, name=body.name.strip(), grade=body.grade, campus_id=body.campus_id)
    db.add(klass)
    db.flush()
    return klass


def update_class(db: Session, tenant_id: uuid.UUID, class_id: uuid.UUID, body: ClassPatch) -> Klass:
    klass = get_class(db, tenant_id, class_id)
    data = body.model_dump(exclude_unset=True)
    if "campus_id" in data:
        _check_campus(db, tenant_id, data["campus_id"])
    for field, value in data.items():
        setattr(klass, field, value)
    db.flush()
    return klass


# —— 班级成员 ——


def list_members(
    db: Session, tenant_id: uuid.UUID, class_id: uuid.UUID, role: MemberRole | None = None
) -> list[MemberOut]:
    get_class(db, tenant_id, class_id)
    stmt = (
        select(ClassMember, User)
        .join(User, User.id == ClassMember.user_id)
        .where(ClassMember.tenant_id == tenant_id, ClassMember.klass_id == class_id)
        .order_by(ClassMember.member_role.desc(), User.username, User.name)
    )
    if role:
        stmt = stmt.where(ClassMember.member_role == role)
    return [
        MemberOut(user=to_user_out(u), member_role=m.member_role, subject=m.subject)
        for m, u in db.execute(stmt)
    ]


def add_member(
    db: Session,
    tenant_id: uuid.UUID,
    class_id: uuid.UUID,
    user_id: uuid.UUID,
    member_role: MemberRole,
    subject: str | None = None,
) -> ClassMember:
    get_class(db, tenant_id, class_id)
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    if user is None:
        raise NotFound("账号不存在")
    needed = Role.TEACHER if member_role == MemberRole.TEACHER else Role.STUDENT
    if not user.has_role(needed):
        raise AppError("账号身份和班级角色不匹配")
    existing = db.scalar(
        select(ClassMember).where(ClassMember.klass_id == class_id, ClassMember.user_id == user_id)
    )
    if existing:
        existing.member_role, existing.subject = member_role, subject
        return existing
    member = ClassMember(
        tenant_id=tenant_id, klass_id=class_id, user_id=user_id, member_role=member_role, subject=subject
    )
    db.add(member)
    db.flush()
    return member


def remove_member(db: Session, tenant_id: uuid.UUID, class_id: uuid.UUID, user_id: uuid.UUID) -> None:
    member = db.scalar(
        select(ClassMember).where(
            ClassMember.tenant_id == tenant_id,
            ClassMember.klass_id == class_id,
            ClassMember.user_id == user_id,
        )
    )
    if member is None:
        raise NotFound("该成员不在班级里")
    db.delete(member)


def class_ids_of(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, role: MemberRole) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(ClassMember.klass_id).where(
                ClassMember.tenant_id == tenant_id,
                ClassMember.user_id == user_id,
                ClassMember.member_role == role,
            )
        )
    )


def class_names(db: Session, tenant_id: uuid.UUID, class_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not class_ids:
        return {}
    rows = db.execute(
        select(Klass.id, Klass.name).where(Klass.tenant_id == tenant_id, Klass.id.in_(class_ids))
    )
    return {cid: name for cid, name in rows}


def students_in_classes(
    db: Session, tenant_id: uuid.UUID, class_ids: list[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """这些班级里的学生，返回（学生 ID，班级 ID）。"""
    if not class_ids:
        return []
    rows = db.execute(
        select(ClassMember.user_id, ClassMember.klass_id)
        .join(User, User.id == ClassMember.user_id)
        .where(
            ClassMember.tenant_id == tenant_id,
            ClassMember.klass_id.in_(class_ids),
            ClassMember.member_role == MemberRole.STUDENT,
            User.active.is_(True),
        )
        .order_by(ClassMember.created_at)
    )
    return [(uid, kid) for uid, kid in rows]


def teachers_of_student(db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID) -> list[uuid.UUID]:
    """学生所在班级的全部任课老师。"""
    class_ids = class_ids_of(db, tenant_id, student_id, MemberRole.STUDENT)
    if not class_ids:
        return []
    return list(
        db.scalars(
            select(ClassMember.user_id)
            .where(
                ClassMember.tenant_id == tenant_id,
                ClassMember.klass_id.in_(class_ids),
                ClassMember.member_role == MemberRole.TEACHER,
            )
            .distinct()
        )
    )


def org_admins(db: Session, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(User.id).where(
                User.tenant_id == tenant_id, str(Role.ORG_ADMIN) == any_(User.roles), User.active.is_(True)
            )
        )
    )


# —— 老师和学生 ——


def get_user(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    if user is None:
        raise NotFound("账号不存在")
    return user


def list_users(
    db: Session, tenant_id: uuid.UUID, role: Role, *, class_id: uuid.UUID | None = None, q: str | None = None
) -> list[User]:
    stmt = select(User).where(User.tenant_id == tenant_id, str(role) == any_(User.roles))
    if class_id:
        stmt = stmt.join(ClassMember, ClassMember.user_id == User.id).where(ClassMember.klass_id == class_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.username.ilike(like)))
    return list(db.scalars(stmt.order_by(User.username, User.name).limit(500)))


def create_teacher(db: Session, tenant_id: uuid.UUID, body: TeacherIn) -> User:
    sms.require_password_if_disabled(body.password)
    quota.ensure_seat(db, tenant_id, Role.TEACHER)
    roles = [Role.TEACHER, Role.ORG_ADMIN] if body.is_org_admin else [Role.TEACHER]
    return iam.create_user(
        db, tenant_id=tenant_id, name=body.name, roles=roles, phone=body.phone, password=body.password
    )


def create_student(db: Session, tenant_id: uuid.UUID, body: StudentIn) -> tuple[User, str | None]:
    quota.ensure_seat(db, tenant_id, Role.STUDENT)
    if body.class_id:
        get_class(db, tenant_id, body.class_id)
    generated = None if body.password else generate_password()
    user = iam.create_user(
        db,
        tenant_id=tenant_id,
        name=body.name,
        roles=[Role.STUDENT],
        username=body.username,
        password=body.password or generated,
        must_change_password=True,
    )
    if body.class_id:
        add_member(db, tenant_id, body.class_id, user.id, MemberRole.STUDENT)
    return user, generated


def set_active(db: Session, tenant_id: uuid.UUID, actor: User, target: User, active: bool) -> None:
    """停用或启用账号。停用的账号不能登录、不占名额，已登录的设备马上退出。"""
    if target.id == actor.id:
        raise AppError("不能停用自己的账号")
    if target.has_role(Role.ORG_ADMIN):
        raise Forbidden("不能停用机构管理员，请联系平台")
    if active == target.active:
        return
    if active:
        role = quota.seat_role(target.roles)
        if role:
            quota.ensure_seat(db, tenant_id, role)
    else:
        target.token_version += 1
    target.active = active
