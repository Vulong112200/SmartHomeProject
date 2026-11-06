"""
Bảo đảm của lớp DB async (SQLAlchemy 2.0 AsyncSession):
  - KHÔNG giữ kết nối DB trong lúc chờ cloud (Tuya/VeSync có khi vài giây);
  - không rò kết nối sau request, kể cả request lỗi 4xx;
  - trợ lý giọng nói chạy nhiều lệnh SONG SONG không dùng chung 1 AsyncSession;
  - DB mất kết nối / pool cạn -> 503 rõ ràng, không 500 trần.
Connector luôn là bản giả (fixture `api`) — không gửi lệnh tới thiết bị thật.
"""
import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeoutError

from app.models.command_log import CommandLogModel
from app.models.schedule import ScheduleModel
from conftest import _req


@pytest.fixture
def pool(api):
    """Đếm kết nối đang bị giữ (checkout - checkin) trên engine async của app."""
    engine = api.async_session.kw["bind"].sync_engine
    state = {"out": 0, "max": 0}

    def checkout(*_):
        state["out"] += 1
        state["max"] = max(state["max"], state["out"])

    def checkin(*_):
        state["out"] -= 1

    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    yield state
    event.remove(engine, "checkout", checkout)
    event.remove(engine, "checkin", checkin)


class _SlowConnector:
    """Ghi lại số kết nối DB đang bị giữ ĐÚNG lúc 'cloud' đang xử lý lệnh."""

    def __init__(self, pool, seen, delay=0.05):
        self.pool, self.seen, self.delay = pool, seen, delay

    async def _cloud(self, device_id):
        self.seen.append((device_id, self.pool["out"]))
        await asyncio.sleep(self.delay)
        return True

    async def turn_on(self, device_id):
        return await self._cloud(device_id)

    async def turn_off(self, device_id):
        return await self._cloud(device_id)

    async def set_mode(self, device_id, mode):
        return await self._cloud(device_id)

    async def get_device_state(self, device_id):
        await self._cloud(device_id)
        return {"device_id": device_id, "status": "ON"}


def test_khong_giu_ket_noi_db_khi_cho_cloud(api, pool, monkeypatch):
    import app.main as main
    seen = []
    monkeypatch.setattr(main.device_manager, "get_connector", lambda brand: _SlowConnector(pool, seen))

    r = _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/lamp-a?action=on")
    assert r.json()["status"] == "success"
    r = _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/door-a/mode?mode=open")
    assert r.json()["status"] == "success"
    r = _req(api.as_user("kid1"), "GET", "/api/devices/tuya/lamp-a/status?fresh=1")
    assert r.json()["data"]["status"] == "ON"

    assert [d for d, _ in seen] == ["lamp-a", "door-a", "lamp-a"]
    assert all(out == 0 for _, out in seen), seen  # 0 kết nối bị giữ trong lúc chờ cloud
    assert pool["out"] == 0


def test_khong_ro_ket_noi_sau_request_ke_ca_loi(api, pool):
    calls = [
        ("kid1", "GET", "/api/devices", 200),
        ("kid1", "GET", "/api/test-control/tuya/lamp-b?action=on", 403),   # ngoài khu
        ("kid1", "GET", "/api/test-control/tuya/khong-co?action=on", 404),
        ("kid1", "GET", "/api/test-control/tuya/lamp-a?action=toggle", 400),
        ("kid1", "GET", "/api/me", 200),
        ("kid1", "GET", "/api/history?sync=0", 200),
        ("guest1", "POST", "/api/scenes", 403),
        ("owner", "GET", "/api/members", 200),
        ("owner", "PATCH", "/api/members/kid1", 400),  # zone_ids không tồn tại
    ]
    for user, method, path, code in calls:
        kw = {"json": {"zone_ids": [999]}} if method == "PATCH" else {}
        if method == "POST":
            kw = {"json": {"name": "x", "actions": []}}
        r = _req(api.as_user(user, is_admin=(user == "owner")), method, path, **kw)
        assert r.status_code == code, (path, r.status_code, r.text)
    assert pool["out"] == 0
    assert pool["max"] >= 1


def test_tro_ly_nhieu_lenh_song_song_moi_lenh_mot_session(api, pool, monkeypatch):
    """Nhiều lệnh thiết bị + nhiều lịch trong 1 câu: không lỗi 'concurrent operations',
    mỗi lệnh có đúng 1 dòng lịch sử, lịch được tạo đủ, kết quả giữ đúng thứ tự."""
    import app.main as main
    seen = []
    monkeypatch.setattr(main.device_manager, "get_connector", lambda brand: _SlowConnector(pool, seen))

    async def fake_exec(brand, device_id, action_type, action_value, invalidate_cache=None):
        connector = main.device_manager.get_connector(brand)
        return await (connector.turn_on(device_id) if action_type == "on" else connector.turn_off(device_id))
    monkeypatch.setattr(main, "execute_schedule_action", fake_exec)

    api.ai_reply["actions"] = [
        {"id": "lamp-a", "action": "on"},
        {"intent": "schedule", "id": "lamp-a", "action": "off", "time": "22:00"},
        {"id": "lamp-b", "action": "on"},
        {"intent": "schedule", "id": "lamp-b", "action": "on", "time": "06:30"},
    ]
    r = _req(api.as_user("owner", is_admin=True), "POST", "/api/ai/parse",
             json={"text": "bật đèn khách và đèn ngủ rồi hẹn giờ"})
    assert r.status_code == 200, r.text
    results = r.json()["execution_results"]
    assert [r["success"] for r in results] == [True, True, True, True], results
    assert results[1]["action"].startswith("Đã hẹn") and results[3]["action"].startswith("Đã hẹn")
    assert sorted(d for d, _ in seen) == ["lamp-a", "lamp-b"]

    logs = api.db.query(CommandLogModel).filter(CommandLogModel.source == "voice").all()
    assert sorted(l.device_id for l in logs) == ["lamp-a", "lamp-b"]
    assert sorted(s.time for s in api.db.query(ScheduleModel).all()) == ["06:30", "22:00"]
    assert pool["out"] == 0


def test_tao_lich_bang_giong_noi_loi_khong_lam_hong_lenh_cung_cau(api, monkeypatch):
    """Lịch lỗi khi ghi DB: lệnh thiết bị trong CÙNG câu vẫn chạy (rollback không được
    expire thiết bị/thành viên mà lệnh sau còn dùng)."""
    import app.main as main

    async def broken_row(db, **kw):
        db.add(ScheduleModel(**{**kw, "time": None}))  # vi phạm NOT NULL -> lỗi lúc commit
        await db.commit()
    monkeypatch.setattr(main, "_create_schedule_row", broken_row)

    api.ai_reply["actions"] = [
        {"intent": "schedule", "id": "lamp-a", "action": "off", "time": "22:00"},
        {"id": "lamp-a", "action": "on"},
    ]
    r = _req(api.as_user("kid1"), "POST", "/api/ai/parse", json={"text": "hẹn tắt đèn và bật đèn"})
    assert r.status_code == 200, r.text
    sched, act = r.json()["execution_results"]
    assert sched["success"] is False and "Lỗi hẹn giờ" in sched["action"]
    assert act["success"] is True
    assert ("tuya", "lamp-a", "on", None) in api.sent


class _DeadSession:
    """Session giả: mọi truy vấn ném lỗi như khi Postgres/pooler rớt."""

    def __init__(self, exc):
        self.exc = exc

    async def execute(self, *a, **k):
        raise self.exc

    async def commit(self):
        raise self.exc

    async def rollback(self):
        pass


@pytest.mark.parametrize("exc", [
    OperationalError("SELECT 1", {}, Exception("connection refused")),
    PoolTimeoutError("QueuePool limit of size 5 overflow 5 reached"),
    TimeoutError("connect timeout"),
])
def test_db_mat_ket_noi_tra_503_ro_rang(api, exc):
    import app.main as main
    from app.core.database import get_db

    async def dead_db():
        yield _DeadSession(exc)

    main.app.dependency_overrides[get_db] = dead_db
    r = _req(api.as_user("kid1"), "GET", "/api/devices")
    assert r.status_code == 503
    assert r.json()["status"] == "error" and "cơ sở dữ liệu" in r.json()["message"]
    # /health không phụ thuộc DB — vẫn 200 cho UptimeRobot.
    assert _req(api.as_user("kid1"), "GET", "/health").status_code == 200


def test_ghi_lich_su_loi_khong_lam_hong_lenh(api, monkeypatch):
    """Lệnh đã chạy thành công thì vẫn báo thành công dù DB ghi lịch sử rớt."""
    import app.main as main

    def broken_factory():
        raise OperationalError("INSERT", {}, Exception("server closed the connection"))
    monkeypatch.setattr(main, "_realtime_session", broken_factory)

    r = _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/lamp-a?action=on")
    assert r.status_code == 200 and r.json()["status"] == "success"
    assert ("tuya", "lamp-a", "on", None) in api.sent
