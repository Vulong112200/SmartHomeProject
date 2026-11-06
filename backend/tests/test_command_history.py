"""
Lịch sử lệnh điều khiển: ai bấm, bấm từ đâu, lúc nào; và sự kiện ngoài app
(nút vật lý / app Smart Life / VeSync). Không test nào gọi Tuya/VeSync thật.
"""
from types import SimpleNamespace as D

import pytest

from conftest import _req, _voice
from app.models.command_log import CommandLogModel
from app.services import command_log, device_history


@pytest.fixture(autouse=True)
def _reset_module_state():
    command_log._last_sent.clear()
    device_history._last_sync.clear()
    device_history._vesync_seen.clear()
    yield


def _history(api, user="owner1", is_admin=True, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = _req(api.as_user(user, is_admin=is_admin), "GET", f"/api/history?{q}")
    assert r.status_code == 200, r.text
    return r.json()["data"]


# =========================================================
# Lệnh do hệ thống gửi
# =========================================================
def test_lenh_tu_app_ghi_nguoi_bam_nguon_va_ket_qua(api):
    _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/lamp-a?action=on")
    _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/door-a/mode?mode=close&via=widget")
    rows = _history(api)
    assert [(r["device_id"], r["action_label"], r["source"], r["user_name"], r["success"]) for r in rows] == [
        ("door-a", "Đóng", "widget", "kid1", True),
        ("lamp-a", "Bật", "app", "kid1", True),
    ]
    assert rows[0]["device_name"] == "Cửa cuốn" and rows[0]["at_ms"] >= rows[1]["at_ms"]


def test_client_khong_gia_duoc_nguon_ngoai_danh_sach(api):
    _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/lamp-a?action=on&via=schedule")
    assert _history(api)[0]["source"] == "app"


def test_lenh_giong_noi_ghi_cau_noi(api):
    api.ai_reply["actions"] = [{"brand": "tuya", "id": "lamp-a", "action": "on", "mode": None}]
    _voice(api, "kid1", "bật đèn khách và đèn ngủ")
    row = _history(api)[0]
    assert (row["source"], row["user_name"], row["action_label"]) == ("voice", "kid1", "Bật")
    assert "bật đèn khách" in row["detail"]


def test_kich_ban_ghi_tung_hanh_dong_kem_ten_kich_ban(api):
    body = {"name": "Đi ngủ", "actions": [{"device_id": "lamp-a", "action_type": "off"},
                                          {"device_id": "lamp-b", "action_type": "off"}]}
    sid = _req(api.as_user("owner1", is_admin=True), "POST", "/api/scenes", json=body).json()["data"]["id"]
    _req(api.as_user("owner1", is_admin=True), "POST", f"/api/scenes/{sid}/run")
    rows = _history(api)
    assert {r["device_id"] for r in rows} == {"lamp-a", "lamp-b"}
    assert all(r["source"] == "scene" and "Đi ngủ" in r["detail"] for r in rows)


def test_kid_chi_thay_lich_su_thiet_bi_trong_khu(api):
    _req(api.as_user("owner1", is_admin=True), "GET", "/api/test-control/tuya/lamp-b?action=on")
    _req(api.as_user("owner1", is_admin=True), "GET", "/api/test-control/tuya/lamp-a?action=on")
    assert [r["device_id"] for r in _history(api, "kid1", is_admin=False)] == ["lamp-a"]
    assert _req(api.as_user("kid1"), "GET", "/api/history?device_id=lamp-b").status_code == 403


def test_phan_trang_bang_before_ms(api):
    for _ in range(3):
        _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/lamp-a?action=on")
    page1 = _history(api, limit=2)
    page2 = _history(api, limit=2, before_ms=page1[-1]["at_ms"])
    assert len(page1) == 2 and all(r["at_ms"] < page1[-1]["at_ms"] for r in page2)


def test_lich_hen_tu_chay_ghi_nguon_schedule_khong_co_nguoi(api, monkeypatch):
    import asyncio

    from app.models.schedule import ScheduleModel
    from app.services import scheduler

    async def fake_exec(*a, **k):
        return True

    monkeypatch.setattr(scheduler, "execute_schedule_action", fake_exec)
    sch = ScheduleModel(id=1, name="Sáng", brand="tuya", device_id="lamp-a", action_type="on",
                        action_value=None, time="06:00", days="")
    asyncio.run(scheduler._fire(api.db, sch, "on", None, "Lịch “Sáng” lúc 06:00", None))
    row = _history(api)[0]
    assert (row["source"], row["user_name"], row["success"]) == ("schedule", None, True)


def test_loi_ghi_lich_su_khong_lam_hong_lenh(api, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db hỏng")

    monkeypatch.setattr(command_log, "CommandLogModel", boom)
    r = _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/lamp-a?action=on")
    assert r.json()["status"] == "success" and api.sent == [("tuya", "lamp-a", "on", None)]


# =========================================================
# Nhật ký Tuya: phân loại nguồn (dữ liệu mẫu theo nhật ký THẬT 2026-11-04/05)
# =========================================================
DOOR = D(id="door", name="Cửa cuốn", brand="tuya", category="curtain")
FEEDER = D(id="feeder", name="Máy cho mèo ăn", brand="rojeco", category="feeder")


def _log(t, code, value, src="1"):
    return {"event_time": t, "code": code, "value": value, "event_from": src}


def test_phan_loai_nhat_ky_tuya():
    commands = [
        _log(1_000_000, "control", "open", "2"),            # app Smart Life
        _log(2_000_000, "control", "close", "cloud2cloud"),  # backend này -> bỏ
    ]
    reports = [
        _log(1_001_500, "control", "open"),     # báo lại lệnh Smart Life -> bỏ
        _log(2_001_000, "control", "close"),    # báo lại lệnh backend -> bỏ
        _log(3_000_000, "control", "close"),    # không có lệnh -> nút vật lý
        _log(3_004_000, "control", "stop"),
        _log(3_100_000, "remote_list", "AA=="),  # nhiễu -> bỏ
    ]
    ev = device_history.classify_tuya_logs(DOOR, commands, reports)
    got = sorted((e["at_ms"], e["source"], e["action_label"]) for e in ev)
    assert got == [
        (1_000_000, "tuya_app", "Mở"),
        (3_000_000, "device", "Đóng"),
        (3_004_000, "device", "Dừng"),
    ]
    assert "cuối hành trình" in next(e for e in ev if e["action_label"] == "Dừng")["detail"]


def test_may_cho_an_tu_chay_theo_lich_trong_may():
    reports = [_log(7_000_000, "feed_report", 1)]
    ev = device_history.classify_tuya_logs(FEEDER, [], reports)
    assert [(e["source"], e["action_label"]) for e in ev] == [("device", "Đã cho ăn 1 phần")]
    # Cho ăn bằng app của mình: feed_report tới sau ~1 phút vẫn là "báo lại", không phải nút.
    cmd = [_log(6_950_000, "manual_feed", 1, "cloud2cloud")]
    assert device_history.classify_tuya_logs(FEEDER, cmd, reports) == []


def test_dong_bo_nhat_ky_khong_ghi_trung(api, monkeypatch):
    t = command_log.now_ms() - 60_000

    class LogConnector:
        async def fetch_event_logs(self, device_id, log_type, start, end, size=100):
            if device_id != "door-a":
                return []
            return [] if log_type == 5 else [_log(t, "control", "open")]

    monkeypatch.setattr(device_history.device_manager, "get_connector", lambda brand: LogConnector())
    first = _history(api)
    device_history._last_sync.clear()  # bỏ hạn 60s để đồng bộ lần 2 ngay
    second = _history(api)
    assert [(r["device_id"], r["source"]) for r in first] == [("door-a", "device")]
    assert len(second) == 1


def test_loi_doc_nhat_ky_van_tra_lich_su(api, monkeypatch):
    class Broken:
        async def fetch_event_logs(self, *a, **k):
            return None

    _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/lamp-a?action=on")
    monkeypatch.setattr(device_history.device_manager, "get_connector", lambda brand: Broken())
    assert len(_history(api)) == 1


# =========================================================
# VeSync: phát hiện đổi trạng thái ngoài app
# =========================================================
PURIFIER = D(id="pur", name="Lọc không khí", brand="vesync", category="purifier")


def test_vesync_doi_trang_thai_ngoai_app(api):
    db = api.db
    assert device_history.observe_state(db, PURIFIER, {"status": "OFF"}) is False  # mốc đầu
    assert device_history.observe_state(db, PURIFIER, {"status": "OFF"}) is False  # không đổi
    assert device_history.observe_state(db, PURIFIER, {"status": "ON", "mode": "manual", "speed": 3})
    row = db.query(CommandLogModel).filter_by(device_id="pur").one()
    assert (row.source, row.action_label, row.success) == ("external", "Lọc Cao", None)


def test_vesync_doi_do_chinh_lenh_cua_minh_thi_khong_ghi(api):
    db = api.db
    device_history.observe_state(db, PURIFIER, {"status": "OFF"})
    command_log.mark_sent("pur")
    assert device_history.observe_state(db, PURIFIER, {"status": "ON", "mode": "auto"}) is False
    assert device_history.observe_state(db, PURIFIER, {"status": "offline"}) is False


def test_vesync_doi_do_lenh_cua_worker_tai_nha_thi_khong_ghi(api):
    """Worker hẹn giờ là TIẾN TRÌNH KHÁC: RAM `recently_sent` của API không biết lệnh của
    nó — chỉ dòng lịch sử trong DB cho biết. Không được ghi thêm dòng 'ngoài app'."""
    db = api.db
    device_history._vesync_seen.pop("pur", None)
    command_log._last_sent.pop("pur", None)
    device_history.observe_state(db, PURIFIER, {"status": "OFF"})
    db.add(CommandLogModel(at_ms=command_log.now_ms(), device_id="pur", action_type="on",
                           action_label="Bật", source="schedule", success=True))
    db.commit()
    assert device_history.observe_state(db, PURIFIER, {"status": "ON", "mode": "auto"}) is False
    assert db.query(CommandLogModel).filter_by(device_id="pur", source="external").count() == 0
