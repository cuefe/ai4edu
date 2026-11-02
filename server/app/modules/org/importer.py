"""Excel 批量导入学生。

表头：姓名、学号、班级、初始密码（后两列可选）。学号即登录账号，在机构内唯一。
班级不存在时自动创建；初始密码为空时自动生成，结果里一次性返回。
"""

import io
import re
import uuid

from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.org import service
from app.modules.org.models import Klass
from app.modules.org.schemas import ClassIn, Credential, ImportResultOut, RowError, StudentIn

MAX_ROWS = 2000
COLUMNS = {"姓名": "name", "学号": "username", "班级": "class_name", "初始密码": "password"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,50}$")


def build_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "学生名单"
    ws.append(list(COLUMNS))
    ws.append(["张三", "2026001", "初一(1)班", ""])
    ws.append(["李四", "2026002", "初一(1)班", "abc123"])
    for col, width in zip("ABCD", (12, 16, 16, 14), strict=True):
        ws.column_dimensions[col].width = width
    notes = wb.create_sheet("填写说明")
    for line in [
        "1. 姓名、学号必填；学号就是学生的登录账号，只能用字母、数字、下划线和减号。",
        "2. 班级填写班级名称，不存在会自动创建。",
        "3. 初始密码可不填，系统会自动生成并在导入结果里显示，请下载保存。",
        "4. 已存在的学号会跳过，不会覆盖原账号。",
        f"5. 每次最多导入 {MAX_ROWS} 行。",
    ]:
        notes.append([line])
    notes.column_dimensions["A"].width = 80
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # Excel 把纯数字学号存成浮点数
    return str(value).strip()


def _read_rows(content: bytes) -> list[tuple[int, dict[str, str]]]:
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise AppError("无法读取文件，请上传 .xlsx 格式的 Excel") from exc
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [_cell(v) for v in next(rows, ())]
    index = {COLUMNS[h]: i for i, h in enumerate(header) if h in COLUMNS}
    if "name" not in index or "username" not in index:
        raise AppError("表头需要包含“姓名”和“学号”两列，请使用导入模板")
    result = []
    for row_no, row in enumerate(rows, start=2):
        values = {key: _cell(row[i]) if i < len(row) else "" for key, i in index.items()}
        if not any(values.values()):
            continue
        result.append((row_no, values))
        if len(result) > MAX_ROWS:
            raise AppError(f"每次最多导入 {MAX_ROWS} 行")
    wb.close()
    return result


def import_students(db: Session, tenant_id: uuid.UUID, content: bytes) -> ImportResultOut:
    rows = _read_rows(content)
    classes = {k.name: k.id for k in db.scalars(select(Klass).where(Klass.tenant_id == tenant_id))}
    created, skipped = 0, 0
    errors: list[RowError] = []
    credentials: list[Credential] = []

    for row_no, v in rows:
        name, username, class_name, password = (
            v["name"],
            v["username"],
            v.get("class_name", ""),
            v.get("password", ""),
        )
        if not name or not username:
            errors.append(RowError(row=row_no, message="姓名和学号不能为空"))
            continue
        if not USERNAME_RE.match(username):
            errors.append(RowError(row=row_no, message=f"学号 {username} 含有不支持的字符"))
            continue
        if password and len(password) < 6:
            errors.append(RowError(row=row_no, message="初始密码至少 6 位"))
            continue

        savepoint = db.begin_nested()
        new_class = False
        try:
            class_id = None
            if class_name:
                class_id = classes.get(class_name)
                if class_id is None:
                    class_id = service.create_class(db, tenant_id, ClassIn(name=class_name)).id
                    classes[class_name], new_class = class_id, True
            _, generated = service.create_student(
                db,
                tenant_id,
                StudentIn(name=name, username=username, class_id=class_id, password=password or None),
            )
            savepoint.commit()
        except AppError as exc:
            savepoint.rollback()
            if new_class:
                classes.pop(class_name)  # 这一行新建的班级随回滚一起撤销了
            if exc.code == "username_taken":
                skipped += 1
                errors.append(RowError(row=row_no, message=f"学号 {username} 已存在，已跳过"))
            else:
                errors.append(RowError(row=row_no, message=exc.message))
            continue

        created += 1
        credentials.append(
            Credential(
                name=name, username=username, class_name=class_name or None, password=password or generated
            )
        )

    return ImportResultOut(created=created, skipped=skipped, errors=errors, credentials=credentials)
