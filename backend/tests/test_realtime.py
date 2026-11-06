"""
/ws thời gian thực: ConnectionManager (phát khi đổi, chống bản cũ về muộn,
heartbeat, lỗi 1 kết nối không lan), quyền theo khu (household.realtime_audience)
và luồng thật qua endpoint (xác thực, lệnh → sự kiện, lệnh lỗi không phát).

KHÔNG test nào gửi lệnh tới thiết bị thật — connector luôn là bản giả.
"""
import asyncio
import json
import time

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.household import realtime_audience
from app.models.member import MemberModel
from app.models.zone import ZoneModel
from app.services import realtime
from app.services.realtime import Connection, ConnectionManager


# =========================================================
# Đồ giả
# =========================================================
class FakeWS:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.closed_code = None
        self.fail = fail

    async def send_text(self, text):
        if self.fail:
            raise RuntimeError("broken pipe")
        self.sent.append(json.loads(text))

    async def close(self, code=1000, reason=None):
        self.closed_code = code

    def events(self, name=None):
        return [m for m in self.sent if name is None or m["event"] == name]


def _manager(visible: dict, revoked=()):
    """visible: user_id -> tập device_id được thấy."""
    m = ConnectionManager()
    refreshed = []

    async def audience(device_id, users):
        rev = set(users) & set(revoked)
        ok = {u for u in users if u not in rev and (device_id is None or device_id in visible.get(u, ()))}
        return ok, rev

    async def refresh(device_id, brand, name, max_age):
        refreshed.append((device_id, max_age))

    async def targets():
        return [("door", "tuya", "Cửa cuốn"), ("purifier", "vesync", "Máy lọc")]

    m.configure(audience=audience, refresh=refresh, targets=targets)
    return m, refreshed


def _connect(m, user_id, fail=False):
    ws = FakeWS(fail=fail)
    conn = Connection(ws, user_id)
    m.add(conn)
    return ws, conn


async def _drain(m):
    while m._bg:
        await asyncio.gather(*list(m._bg), return_exceptions=True)


def _run(coro):
    return asyncio.run(coro)


DEV = type("Dev", (), {})


def _device(id_, brand="tuya", category="switch", name="Thiết bị"):
    d = DEV()
    d.id, d.brand, d.category, d.name = id_, brand, category, name
    return d


# =========================================================
# ConnectionManager
# =========================================================
def test_chi_phat_khi_trang_thai_doi():
    async def go():
        m, _ = _manager({"u": {"lamp"}})
        ws, _ = _connect(m, "u")
        m.notify_state("lamp", "tuya", {"device_id": "lamp", "status": "OFF"}, 100)
        m.notify_state("lamp", "tuya", {"device_id": "lamp", "status": "OFF"}, 200)  # y hệt
        m.notify_state("lamp", "tuya", {"device_id": "lamp", "status": "ON"}, 300)
        await _drain(m)
        evs = ws.events(realtime.STATUS_CHANGED)
        assert [e["data"]["state"]["status"] for e in evs] == ["OFF", "ON"]
        e = evs[-1]
        assert e["device_id"] == "lamp" and e["data"]["brand"] == "tuya" and e["data"]["read_at_ms"] == 300
        assert isinstance(e["timestamp"], int)
    _run(go())


def test_lan_doc_cu_ve_muon_khong_ghi_de_trang_thai_moi():
    async def go():
        m, _ = _manager({"u": {"lamp"}})
        ws, _ = _connect(m, "u")
        m.notify_state("lamp", "tuya", {"status": "ON"}, 500)
        m.notify_state("lamp", "tuya", {"status": "OFF"}, 400)  # bắt đầu đọc TRƯỚC, về SAU
        await _drain(m)
        assert [e["data"]["state"]["status"] for e in ws.events(realtime.STATUS_CHANGED)] == ["ON"]
    _run(go())


def test_su_kien_offline_va_online():
    async def go():
        m, _ = _manager({"u": {"door"}})
        ws, _ = _connect(m, "u")
        m.notify_state("door", "tuya", {"status": "OFF", "door_state": "closed"}, 1)
        m.notify_state("door", "tuya", {"status": "offline", "door_state": "unknown"}, 2)
        m.notify_state("door", "tuya", {"status": "offline", "door_state": "unknown"}, 3)
        m.notify_state("door", "tuya", {"status": "ON", "door_state": "open"}, 4)
        await _drain(m)
        names = [e["event"] for e in ws.sent]
        assert names.count(realtime.DEVICE_OFFLINE) == 1
        assert names.count(realtime.DEVICE_ONLINE) == 1
        assert names.index(realtime.DEVICE_OFFLINE) < names.index(realtime.DEVICE_ONLINE)
    _run(go())


def test_chi_nguoi_duoc_quyen_nhan_va_nhieu_may_cung_tai_khoan_deu_nhan():
    async def go():
        m, _ = _manager({"owner": {"lamp-a", "lamp-b"}, "kid": {"lamp-a"}})
        owner_ws, _ = _connect(m, "owner")
        kid_phone, _ = _connect(m, "kid")
        kid_tablet, _ = _connect(m, "kid")
        m.notify_state("lamp-b", "tuya", {"status": "ON"}, 1)
        m.notify_state("lamp-a", "tuya", {"status": "ON"}, 2)
        await _drain(m)
        assert {e["device_id"] for e in owner_ws.sent} == {"lamp-a", "lamp-b"}
        for ws in (kid_phone, kid_tablet):
            assert {e["device_id"] for e in ws.sent} == {"lamp-a"}
    _run(go())


def test_ket_noi_loi_bi_go_khong_anh_huong_nguoi_khac():
    async def go():
        m, _ = _manager({"a": {"lamp"}, "b": {"lamp"}})
        broken, _ = _connect(m, "a", fail=True)
        good, _ = _connect(m, "b")
        m.notify_state("lamp", "tuya", {"status": "ON"}, 1)
        await _drain(m)
        assert len(good.events(realtime.STATUS_CHANGED)) == 1
        assert m.count == 1 and broken.closed_code == 1011
        m.notify_state("lamp", "tuya", {"status": "OFF"}, 2)
        await _drain(m)
        assert len(good.events(realtime.STATUS_CHANGED)) == 2
    _run(go())


def test_khong_xac_dinh_duoc_quyen_thi_khong_gui():
    async def go():
        m = ConnectionManager()

        async def broken_audience(device_id, users):
            raise RuntimeError("DB down")

        async def noop(*a):
            return []
        m.configure(audience=broken_audience, refresh=noop, targets=noop)
        ws, _ = _connect(m, "u")
        m.notify_state("lamp", "tuya", {"status": "ON"}, 1)
        await _drain(m)
        assert ws.sent == []
    _run(go())


def test_thanh_vien_khong_con_active_bi_ngat_4403():
    async def go():
        m, _ = _manager({"kid": {"lamp"}, "mom": {"lamp"}}, revoked={"kid"})
        kid, _ = _connect(m, "kid")
        mom, _ = _connect(m, "mom")
        m.notify_state("lamp", "tuya", {"status": "ON"}, 1)
        await _drain(m)
        assert kid.sent == [] and kid.closed_code == realtime.CLOSE_FORBIDDEN
        assert len(mom.sent) == 1 and m.count == 1
    _run(go())


def test_lenh_loi_khong_phat_va_khong_doc_lai(monkeypatch):
    monkeypatch.setattr(realtime, "FOLLOWUP_DELAYS", (0.01,))

    async def go():
        m, refreshed = _manager({"u": {"lamp"}})
        ws, _ = _connect(m, "u")
        m.notify_command(_device("lamp"), action_type="on", action_value=None,
                         source="app", success=False)
        m.notify_command(_device("lamp"), action_type="on", action_value=None,
                         source="app", success=None)
        await asyncio.sleep(0.05)
        await _drain(m)
        assert ws.sent == [] and refreshed == [] and not m._followups
    _run(go())


def test_lenh_thanh_cong_phat_command_completed_roi_doc_lai(monkeypatch):
    monkeypatch.setattr(realtime, "FOLLOWUP_DELAYS", (0.01, 0.02))
    monkeypatch.setattr(realtime, "DOOR_SETTLE_DELAY", 0.03)

    async def go():
        m, refreshed = _manager({"u": {"lamp", "door"}})
        ws, _ = _connect(m, "u")
        member = type("M", (), {"display_name": "Mẹ", "email": "me@x", "user_id": "u"})()
        m.notify_command(_device("lamp"), action_type="on", action_value=None,
                         source="voice", success=True, member=member)
        m.notify_command(_device("door", category="curtain"), action_type="mode",
                         action_value="open", source="schedule", success=True)
        await asyncio.sleep(0.1)
        await _drain(m)
        done = ws.events(realtime.COMMAND_COMPLETED)
        lamp = next(e for e in done if e["device_id"] == "lamp")["data"]
        assert lamp["source"] == "voice" and lamp["user_name"] == "Mẹ"
        assert lamp["action_label"] == "Bật" and lamp["success"] is True
        door = next(e for e in done if e["device_id"] == "door")["data"]
        assert door["action_label"] == "Mở" and door["user_name"] is None
        # Đèn: 2 nhịp đọc lại; cửa: thêm 1 nhịp sau khi hết hành trình 30s.
        assert [r for r in refreshed if r[0] == "lamp"] == [("lamp", 1.2)] * 2
        assert len([r for r in refreshed if r[0] == "door"]) == 3
    _run(go())


def test_lenh_moi_thay_lich_doc_lai_cua_lenh_cu(monkeypatch):
    monkeypatch.setattr(realtime, "FOLLOWUP_DELAYS", (0.05,))

    async def go():
        m, refreshed = _manager({"u": {"lamp"}})
        _connect(m, "u")
        for _ in range(3):
            m.notify_command(_device("lamp"), action_type="on", action_value=None,
                             source="app", success=True)
        await asyncio.sleep(0.1)
        assert refreshed == [("lamp", 1.2)]
    _run(go())


def test_khong_ai_ket_noi_thi_khong_doc_lai_va_watcher_khong_chay():
    async def go():
        m, refreshed = _manager({})
        m.notify_command(_device("lamp"), action_type="on", action_value=None,
                         source="app", success=True)
        assert not m._followups and not m._bg
        assert await m.watch_once() == 0 and refreshed == []
    _run(go())


def test_watcher_doc_thiet_bi_theo_doi_khi_co_ket_noi():
    async def go():
        m, refreshed = _manager({"u": set()})
        _connect(m, "u")
        assert await m.watch_once() == 2
        assert {r[0] for r in refreshed} == {"door", "purifier"}
        assert all(r[1] == realtime.WATCH_INTERVAL - 2 for r in refreshed)
    _run(go())


def test_heartbeat_ngat_ket_noi_chet_va_ping_ket_noi_song():
    async def go():
        m, _ = _manager({})
        dead, dead_conn = _connect(m, "a")
        alive, _ = _connect(m, "b")
        dead_conn.last_seen = time.monotonic() - realtime.DEAD_AFTER - 1
        await m.heartbeat_once()
        assert dead.closed_code == 1001 and dead.sent == []
        assert [e["event"] for e in alive.sent] == [realtime.PING]
        assert m.count == 1
    _run(go())


def test_revalidate_ngat_thanh_vien_bi_chan():
    async def go():
        m, _ = _manager({}, revoked={"kid"})
        kid, _ = _connect(m, "kid")
        mom, _ = _connect(m, "mom")
        await m.revalidate_users()
        assert kid.closed_code == realtime.CLOSE_FORBIDDEN and mom.closed_code is None
    _run(go())


# =========================================================
# Quyền: household.realtime_audience (DB thật, SQLite tạm)
# =========================================================
def test_audience_theo_khu_va_trang_thai_thanh_vien(api):
    db = api.db
    db.add_all([
        MemberModel(user_id="mom", email="mom@x.test", role="adult", status="active"),
        MemberModel(user_id="bad", email="bad@x.test", role="adult", status="blocked"),
        MemberModel(user_id="new", email="new@x.test", role="guest", status="pending"),
    ])
    db.commit()
    users = {"mom", "kid1", "bad", "new", "ghost"}

    allowed, revoked = api.call(lambda s: realtime_audience(s, users, "lamp-b"))  # khu B: kid1 không được cấp
    assert allowed == {"mom"}
    assert revoked == {"bad", "new", "ghost"}

    allowed, _ = api.call(lambda s: realtime_audience(s, users, "lamp-a"))
    assert allowed == {"mom", "kid1"}

    # Khu dùng chung: kid thấy mà không cần grant.
    zone_b = db.query(ZoneModel).filter(ZoneModel.name == "Phòng ngủ").one()
    zone_b.is_shared = True
    db.commit()
    allowed, _ = api.call(lambda s: realtime_audience(s, users, "lamp-b"))
    assert allowed == {"mom", "kid1"}

    # device_id None: chỉ kiểm trạng thái thành viên.
    allowed, revoked = api.call(lambda s: realtime_audience(s, users, None))
    assert allowed == {"mom", "kid1"} and revoked == {"bad", "new", "ghost"}


