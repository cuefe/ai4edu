import io

from openpyxl import Workbook, load_workbook

from tests.conftest import auth, make_tenant, student_auth


def _xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(client, headers, content: bytes):
    return client.post(
        "/api/org/students/import",
        headers=headers,
        files={
            "file": (
                "students.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def test_class_teacher_student_flow(client):
    make_tenant("t1", "13811110000")
    admin = auth(client, "13811110000")

    klass = client.post("/api/org/classes", headers=admin, json={"name": "初一(1)班", "grade": "初一"}).json()
    other = client.post("/api/org/classes", headers=admin, json={"name": "初一(2)班", "grade": "初一"}).json()
    dup = client.post("/api/org/classes", headers=admin, json={"name": "初一(1)班"})
    assert dup.status_code == 409

    teacher = client.post(
        "/api/org/teachers",
        headers=admin,
        json={"name": "李老师", "phone": "13822220000", "password": "teach123"},
    ).json()
    assert teacher["phone_masked"] == "138****0000"
    resp = client.post(
        f"/api/org/classes/{klass['id']}/members",
        headers=admin,
        json={"user_id": teacher["id"], "member_role": "teacher", "subject": "数学"},
    )
    assert resp.status_code == 200

    created = client.post(
        "/api/org/students", headers=admin, json={"name": "张三", "username": "s001", "class_id": klass["id"]}
    ).json()
    password = created["initial_password"]
    assert password and len(password) == 8

    # 学生身份不能当老师加进班级
    bad = client.post(
        f"/api/org/classes/{other['id']}/members",
        headers=admin,
        json={"user_id": created["user"]["id"], "member_role": "teacher"},
    )
    assert bad.status_code == 400

    classes = {c["name"]: c for c in client.get("/api/org/classes", headers=admin).json()}
    assert classes["初一(1)班"]["teacher_count"] == 1
    assert classes["初一(1)班"]["student_count"] == 1
    assert classes["初一(2)班"]["student_count"] == 0

    # 老师只能看自己任教的班
    t = auth(client, "13822220000", "teach123")
    mine = client.get("/api/teacher/classes", headers=t).json()
    assert [c["name"] for c in mine] == ["初一(1)班"]
    roster = client.get(f"/api/teacher/classes/{klass['id']}/students", headers=t).json()
    assert [m["user"]["username"] for m in roster] == ["s001"]
    assert client.get(f"/api/teacher/classes/{other['id']}/students", headers=t).status_code == 403
    # 老师不能调用机构管理接口
    assert client.get("/api/org/classes", headers=t).status_code == 403

    # 学生首次登录要求改密码
    login = client.post(
        "/api/auth/login/student", json={"tenant_code": "T1", "username": "s001", "password": password}
    ).json()
    assert login["user"]["must_change_password"] is True
    s = {"Authorization": f"Bearer {login['access_token']}"}
    assert [c["name"] for c in client.get("/api/student/classes", headers=s).json()] == ["初一(1)班"]
    assert client.get("/api/teacher/classes", headers=s).status_code == 403


def test_import_students(client):
    make_tenant("t1", "13811110000")
    admin = auth(client, "13811110000")
    client.post(
        "/api/org/students",
        headers=admin,
        json={"name": "老学生", "username": "2026001", "password": "123456"},
    )

    content = _xlsx(
        [
            ["姓名", "学号", "班级", "初始密码"],
            ["已存在", 2026001, "初一(1)班", ""],  # 学号已存在 → 跳过
            ["张三", 2026002, "初一(1)班", ""],  # 数字学号、班级自动创建、密码自动生成
            ["李四", "2026003", "初一(2)班", "abc123"],
            ["", "2026004", "", ""],  # 缺姓名
            ["王五", "bad id!", "", ""],  # 学号有非法字符
            ["赵六", "2026005", "", "123"],  # 密码太短
            [None, None, None, None],  # 空行忽略
        ]
    )
    result = _upload(client, admin, content).json()
    assert result["created"] == 2
    assert result["skipped"] == 1
    assert sorted(e["row"] for e in result["errors"]) == [2, 5, 6, 7]
    creds = {c["username"]: c for c in result["credentials"]}
    assert set(creds) == {"2026002", "2026003"}
    assert creds["2026003"]["password"] == "abc123"

    classes = {c["name"]: c["student_count"] for c in client.get("/api/org/classes", headers=admin).json()}
    assert classes == {"初一(1)班": 1, "初一(2)班": 1}
    student_auth(client, "t1", "2026002", creds["2026002"]["password"])


def test_import_rejects_bad_files(client):
    make_tenant("t1", "13811110000")
    admin = auth(client, "13811110000")
    assert _upload(client, admin, b"not an excel file").status_code == 400
    assert _upload(client, admin, _xlsx([["名字", "编号"], ["张三", "1"]])).status_code == 400


def test_import_failed_row_does_not_leave_half_created_class(client):
    make_tenant("t1", "13811110000")
    admin = auth(client, "13811110000")
    client.post(
        "/api/org/students", headers=admin, json={"name": "甲", "username": "a1", "password": "123456"}
    )
    # 第一行因学号重复回滚（连同新建的班级），第二行要能重新创建这个班
    result = _upload(
        client, admin, _xlsx([["姓名", "学号", "班级"], ["甲", "a1", "新班"], ["乙", "a2", "新班"]])
    ).json()
    assert result["created"] == 1
    classes = {c["name"]: c["student_count"] for c in client.get("/api/org/classes", headers=admin).json()}
    assert classes == {"新班": 1}


def test_import_template(client):
    make_tenant("t1", "13811110000")
    admin = auth(client, "13811110000")
    resp = client.get("/api/org/students/import-template", headers=admin)
    assert resp.status_code == 200
    ws = load_workbook(io.BytesIO(resp.content)).active
    assert [c.value for c in ws[1]] == ["姓名", "学号", "班级", "初始密码"]


def test_reset_password(client):
    make_tenant("t1", "13811110000")
    admin = auth(client, "13811110000")
    student = client.post(
        "/api/org/students", headers=admin, json={"name": "张三", "username": "s1", "password": "oldpass"}
    ).json()
    old_headers = student_auth(client, "t1", "s1", "oldpass")
    new_pw = client.post(f"/api/org/users/{student['user']['id']}/reset-password", headers=admin).json()[
        "password"
    ]
    assert client.get("/api/me", headers=old_headers).status_code == 401
    student_auth(client, "t1", "s1", new_pw)
