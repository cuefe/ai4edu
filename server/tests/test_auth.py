from app.core.redis import get_redis
from app.core.security import phone_hash
from tests.conftest import auth, make_platform_admin, make_tenant


def test_phone_login_and_me(client):
    make_tenant("t1", "13811110000")
    resp = client.post("/api/auth/login/phone", json={"phone": "138 1111 0000", "password": "admin123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["tenant"]["code"] == "t1"
    assert body["user"]["phone_masked"] == "138****0000"
    assert set(body["user"]["roles"]) == {"org_admin", "teacher"}

    me = client.get("/api/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["name"] == "t1 管理员"


def test_wrong_password_and_lockout(client):
    make_tenant("t1", "13811110000")
    for _ in range(10):
        resp = client.post("/api/auth/login/phone", json={"phone": "13811110000", "password": "bad"})
        assert resp.status_code == 401
        assert resp.json()["code"] == "bad_credentials"
    resp = client.post("/api/auth/login/phone", json={"phone": "13811110000", "password": "admin123"})
    assert resp.status_code == 429


def test_unauthenticated_requests_rejected(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_sms_login(client):
    make_tenant("t1", "13811110000")
    assert client.post("/api/auth/sms/send", json={"phone": "13811110000"}).status_code == 200
    # 60 秒内重复发送被拒绝
    assert client.post("/api/auth/sms/send", json={"phone": "13811110000"}).status_code == 429

    code = get_redis().get(f"sms:code:{phone_hash('13811110000')}")
    assert code and len(code) == 6
    wrong = "000000" if code != "000000" else "111111"
    assert client.post("/api/auth/login/sms", json={"phone": "13811110000", "code": wrong}).status_code == 401
    resp = client.post("/api/auth/login/sms", json={"phone": "13811110000", "code": code})
    assert resp.status_code == 200
    # 验证码只能用一次
    assert client.post("/api/auth/login/sms", json={"phone": "13811110000", "code": code}).status_code == 401


def test_sms_unregistered_phone_does_not_send(client):
    assert client.post("/api/auth/sms/send", json={"phone": "13999999999"}).status_code == 200
    assert get_redis().get(f"sms:code:{phone_hash('13999999999')}") is None


def test_refresh_and_password_change_revokes_old_tokens(client):
    make_tenant("t1", "13811110000")
    first = client.post("/api/auth/login/phone", json={"phone": "13811110000", "password": "admin123"}).json()

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert refreshed.status_code == 200

    headers = {"Authorization": f"Bearer {first['access_token']}"}
    changed = client.post(
        "/api/me/password", headers=headers, json={"old_password": "admin123", "new_password": "newpass1"}
    )
    assert changed.status_code == 200

    # 旧令牌全部失效，新令牌可用
    assert client.get("/api/me", headers=headers).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    new_headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert client.get("/api/me", headers=new_headers).status_code == 200
    assert (
        client.post(
            "/api/auth/login/phone", json={"phone": "13811110000", "password": "newpass1"}
        ).status_code
        == 200
    )


def test_access_token_cannot_be_used_as_refresh(client):
    make_tenant("t1", "13811110000")
    tokens = client.post(
        "/api/auth/login/phone", json={"phone": "13811110000", "password": "admin123"}
    ).json()
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401


def test_platform_admin_login(client):
    make_platform_admin()
    headers = auth(client, "13900000000")
    me = client.get("/api/me", headers=headers).json()
    assert me["tenant"] is None
    assert me["roles"] == ["platform_admin"]
