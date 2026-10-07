import jwt

from opspilot_common.auth import create_system_token, decode_token, get_auth_settings


def _login(client, username, password="password123"):
    return client.post("/auth/login", json={"username": username, "password": password})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_login_success_and_claims(client):
    r = _login(client, "alice")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "customer"
    assert body["user_id"] == 1
    claims = decode_token(body["access_token"])
    assert claims["sub"] == "1"
    assert claims["username"] == "alice"
    assert claims["role"] == "customer"
    assert "exp" in claims


def test_login_staff(client):
    assert _login(client, "staff1").json()["role"] == "staff"


def test_login_wrong_password(client):
    r = _login(client, "alice", "nope")
    assert r.status_code == 401
    assert r.json() == {"error": "invalid_credentials", "message": "Sai tên đăng nhập hoặc mật khẩu"}


def test_login_unknown_user(client):
    assert _login(client, "mallory").status_code == 401


def test_login_validation_error_format(client):
    r = client.post("/auth/login", json={"username": "alice"})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"


def test_me(client):
    token = _login(client, "bob").json()["access_token"]
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "bob"
    assert r.json()["email"] == "bob@example.com"


def test_me_requires_token(client):
    assert client.get("/auth/me").status_code == 401


def test_system_role_cannot_login(client):
    for username in ("system",):
        assert _login(client, username).status_code == 401


def test_forged_system_role_with_user_secret_rejected(client):
    s = get_auth_settings()
    forged = jwt.encode({"sub": "0", "role": "system", "exp": 9999999999}, s.JWT_SECRET, algorithm="HS256")
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_real_system_token_accepted(client):
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {create_system_token()}"})
    assert r.status_code == 200
    assert r.json()["role"] == "system"
