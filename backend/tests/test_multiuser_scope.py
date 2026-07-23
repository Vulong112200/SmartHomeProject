# backend/tests/test_multiuser_scope.py
"""
Kiểm tra cách ly dữ liệu đa người dùng: user A không thấy / không điều khiển
được thiết bị của user B; thiếu token -> 401.

Đặt env TRƯỚC khi import app (database.py đọc DATABASE_URL lúc import; auth đọc
SUPABASE_JWT_SECRET lúc gọi). Dùng TestClient KHÔNG mở lifespan để tránh gọi
mạng tới Tuya/VeSync — các test này dừng ở tầng sở hữu, không chạm connector.
"""
import os
import time

# --- cấu hình môi trường test (phải đặt trước khi import app) ---
_TEST_DB = os.path.join(os.path.dirname(__file__), "_scope_test.db")
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["SUPABASE_JWT_SECRET"] = "test-secret"
os.environ["AUTH_DISABLED"] = "0"
os.environ.setdefault("FERNET_KEY", "")

import asyncio  # noqa: E402

import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402

from app.main import app  # noqa: E402

# Gọi thẳng ASGI app qua ASGITransport (không mở lifespan -> không gọi mạng
# Tuya/VeSync). Tương thích httpx 0.28 (TestClient của Starlette 0.27 thì không).
_transport = httpx.ASGITransport(app=app)


class _Client:
    """Bọc gọn để test viết đồng bộ như requests."""
    def request(self, method, url, **kw):
        async def go():
            async with httpx.AsyncClient(transport=_transport, base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.run(go())

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)


client = _Client()


def _token(sub: str, email: str) -> str:
    payload = {"sub": sub, "email": email, "aud": "authenticated",
               "exp": int(time.time()) + 3600}
    return jwt.encode(payload, "test-secret", algorithm="HS256")


def _auth(sub, email):
    return {"Authorization": f"Bearer {_token(sub, email)}"}


A = ("11111111-1111-1111-1111-111111111111", "a@example.com")
B = ("22222222-2222-2222-2222-222222222222", "b@example.com")


def test_requires_token():
    assert client.get("/api/devices").status_code == 401


def test_devices_are_isolated_per_user():
    # A thêm 1 thiết bị
    r = client.post("/api/devices",
                    params={"id": "dev_a", "name": "Đèn A", "brand": "tuya"},
                    headers=_auth(*A))
    assert r.json()["status"] == "success"
    # B thêm 1 thiết bị khác
    client.post("/api/devices",
                params={"id": "dev_b", "name": "Đèn B", "brand": "tuya"},
                headers=_auth(*B))

    a_ids = {d["id"] for d in client.get("/api/devices", headers=_auth(*A)).json()["data"]}
    b_ids = {d["id"] for d in client.get("/api/devices", headers=_auth(*B)).json()["data"]}
    assert a_ids == {"dev_a"}
    assert b_ids == {"dev_b"}


def test_cannot_control_other_users_device():
    # B cố điều khiển thiết bị của A -> 404 (không phải của B)
    r = client.get("/api/test-control/tuya/dev_a", params={"action": "on"},
                   headers=_auth(*B))
    assert r.status_code == 404
    # B đọc trạng thái thiết bị của A -> 404
    r2 = client.get("/api/devices/tuya/dev_a/status", headers=_auth(*B))
    assert r2.status_code == 404


def test_cannot_schedule_other_users_device():
    body = {"brand": "tuya", "device_id": "dev_a", "action_type": "on", "time": "07:00"}
    r = client.post("/api/schedules", json=body, headers=_auth(*B))
    assert r.status_code == 404


def test_me_reports_admin_flag(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "a@example.com")
    assert client.get("/api/me", headers=_auth(*A)).json()["data"]["is_admin"] is True
    assert client.get("/api/me", headers=_auth(*B)).json()["data"]["is_admin"] is False


@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    if os.path.exists(_TEST_DB):
        try:
            os.remove(_TEST_DB)
        except OSError:
            pass
