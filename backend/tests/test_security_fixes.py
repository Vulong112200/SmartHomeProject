"""
Các lỗi vượt quyền / nguy hiểm vật lý tìm được khi rà soát (đợt 2).

KHÔNG gọi thiết bị thật: `execute_schedule_action` (đường thi hành chung) và
AI parser đều bị thay bằng bộ ghi giả trong mọi test qua HTTP.
"""
import asyncio
from types import SimpleNamespace as D

import pytest

from conftest import _req, _voice
from app.models.schedule import ScheduleModel
from app.services.device_actions import normalize_action
from app.services.local_parser import parse_command_locally
from app.services.rojeco_connector import RojecoConnector
from app.services.tuya_connector import TuyaConnector


# " và " ép câu đi đường AI (câu phức) — đúng cách kid lách qua local parser.
FORCE_AI = "bật đèn và tắt đèn"


# =========================================================
# 1. Trợ lý AI chỉ chạm thiết bị trong khu được cấp
# =========================================================
def test_ai_khong_dieu_khien_duoc_thiet_bi_ngoai_khu(api):
    api.ai_reply["actions"] = [{"brand": "tuya", "id": "lamp-b", "action": "on", "mode": None}]
    res = _voice(api, "kid1", FORCE_AI)
    assert res["execution_results"][0]["success"] is False
    assert api.sent == []


def test_ai_brand_lay_tu_db_khong_tin_ai(api):
    api.ai_reply["actions"] = [{"brand": "vesync", "id": "lamp-a", "action": "on", "mode": None}]
    _voice(api, "kid1", FORCE_AI)
    assert api.sent == [("tuya", "lamp-a", "on", None)]


def test_ai_bat_cua_cuon_bi_tu_choi(api):
    # "bật" cửa = mở cửa: không được đoán, phải nói rõ mở/đóng/dừng.
    api.ai_reply["actions"] = [{"brand": "tuya", "id": "door-a", "action": "on", "mode": None}]
    res = _voice(api, "kid1", FORCE_AI)
    assert res["execution_results"][0]["success"] is False
    assert api.sent == []


@pytest.mark.parametrize("reply", [{"action": "on"}, None, "on", [None, 3]])
def test_ai_tra_ve_khong_phai_list_khong_lam_sap_endpoint(api, reply):
    api.ai_reply["actions"] = reply
    res = _voice(api, "kid1", FORCE_AI)
    assert res["execution_results"] == []
    assert api.sent == []


# =========================================================
# 2. Lịch tạo bằng giọng nói theo đúng luật của POST /api/schedules
# =========================================================
def _schedule_intent(device_id):
    return [{"intent": "schedule", "brand": "tuya", "id": device_id, "action": "on", "mode": None,
             "time": "16:30", "end_time": None, "end_action": None, "end_mode": None,
             "day_offset": 0, "recurring_daily": True}]


def test_guest_khong_tao_duoc_lich_bang_giong_noi(api):
    api.ai_reply["actions"] = _schedule_intent("lamp-a")
    res = _voice(api, "guest1", "hẹn 16 giờ 30 bật đèn và tắt đèn")
    assert res["execution_results"][0]["success"] is False
    assert api.db.query(ScheduleModel).count() == 0


def test_kid_khong_hen_gio_duoc_thiet_bi_ngoai_khu(api):
    api.ai_reply["actions"] = _schedule_intent("lamp-b")
    res = _voice(api, "kid1", "hẹn 16 giờ 30 bật đèn và tắt đèn")
    assert res["execution_results"][0]["success"] is False
    assert api.db.query(ScheduleModel).count() == 0


def test_kid_hen_gio_trong_khu_thi_duoc_va_brand_tu_db(api):
    intent = _schedule_intent("lamp-a")
    intent[0]["brand"] = "vesync"
    api.ai_reply["actions"] = intent
    res = _voice(api, "kid1", "hẹn 16 giờ 30 bật đèn và tắt đèn")
    assert res["execution_results"][0]["success"] is True
    sch = api.db.query(ScheduleModel).one()
    assert (sch.device_id, sch.brand, sch.created_by) == ("lamp-a", "tuya", "kid1")


# =========================================================
# 3 + 4. Sửa lịch
# =========================================================
def _kid_schedule(api, last_fired="2026-11-04"):
    sch = ScheduleModel(name="x", brand="tuya", device_id="lamp-a", action_type="on", time="07:00",
                        days="", enabled=True, created_by="kid1", last_fired_date=last_fired)
    api.db.add(sch)
    api.db.commit()
    return sch.id


def test_kid_khong_chuyen_duoc_lich_sang_thiet_bi_ngoai_khu(api):
    sid = _kid_schedule(api)
    r = _req(api.as_user("kid1"), "PATCH", f"/api/schedules/{sid}", json={"device_id": "lamp-b"})
    assert r.status_code == 403
    api.db.expire_all()
    assert api.db.get(ScheduleModel, sid).device_id == "lamp-a"


def test_doi_ten_lich_khong_lam_lich_chay_lai(api):
    sid = _kid_schedule(api)
    # App gửi lại đủ form (cùng giờ) khi chỉ đổi tên.
    r = _req(api.as_user("kid1"), "PATCH", f"/api/schedules/{sid}",
             json={"name": "Tên mới", "time": "07:00", "end_time": None, "enabled": True})
    assert r.json()["status"] == "success"
    api.db.expire_all()
    assert api.db.get(ScheduleModel, sid).last_fired_date == "2026-11-04"


def test_doi_gio_that_su_thi_cho_chay_lai(api):
    sid = _kid_schedule(api)
    _req(api.as_user("kid1"), "PATCH", f"/api/schedules/{sid}", json={"time": "08:00"})
    api.db.expire_all()
    assert api.db.get(ScheduleModel, sid).last_fired_date is None


# =========================================================
# 5. Action gõ sai KHÔNG được thành "tắt" (= đóng cửa)
# =========================================================
@pytest.mark.parametrize("action", ["open", "toggle", "ON", ""])
def test_test_control_action_la_tra_400(api, action):
    r = _req(api.as_user("kid1"), "GET", f"/api/test-control/tuya/door-a?action={action}")
    assert r.status_code == 400


def test_them_thiet_bi_category_sai_bi_tu_choi(api):
    r = _req(api.as_user("owner1", is_admin=True), "POST",
             "/api/devices?id=x1&name=Bơm&brand=tuya&category=toaster")
    assert r.json()["status"] == "error"


# =========================================================
# Unit: chuẩn hóa hành động theo loại
# =========================================================
DOOR = D(name="Cửa", brand="tuya", category="curtain")
FEEDER = D(name="Máy cho ăn", brand="rojeco", category="feeder")
PUMP = D(name="Máy bơm", brand="tuya", category="switch")
PURIFIER = D(name="Lọc", brand="vesync", category="purifier")


def test_normalize_chap_nhan_tu_vung_parser_va_ai():
    assert normalize_action(PUMP, "turn_on", None) == ("on", None)
    assert normalize_action(PUMP, "off", None) == ("off", None)
    assert normalize_action(PUMP, "set_mode", "on") == ("on", None)
    assert normalize_action(DOOR, "set_mode", "close") == ("mode", "close")
    assert normalize_action(PURIFIER, "set_mode", "auto") == ("mode", "auto")
    assert normalize_action(FEEDER, "set_mode", "2") == ("mode", "2")


@pytest.mark.parametrize("device, verb, mode", [
    (DOOR, "on", None),          # bật cửa = mở cửa: không đoán
    (DOOR, "turn_off", None),
    (DOOR, "set_mode", "explode"),
    (FEEDER, "set_mode", "40"),  # đổ cả khay hạt
    (FEEDER, "on", None),
    (PUMP, "set_mode", "open"),
    (PURIFIER, "toggle", None),
])
def test_normalize_tu_choi_hanh_dong_sai_loai(device, verb, mode):
    with pytest.raises(ValueError):
        normalize_action(device, verb, mode)


# =========================================================
# Unit: "tắt hết" không đụng cửa / máy cho ăn
# =========================================================
HOME = [
    D(id="door", name="Cửa cuốn", brand="tuya", category=None),
    D(id="pump", name="Máy bơm tăng áp", brand="tuya", category="switch"),
    D(id="feed", name="Máy cho mèo ăn", brand="rojeco", category=None),
    D(id="air", name="Lọc không khí", brand="vesync", category=None),
]


def test_tat_het_chi_tat_may_loc_va_cong_tac():
    acts = parse_command_locally("tắt hết", HOME)
    assert sorted(a["id"] for a in acts) == ["air", "pump"]
    assert all(a["action"] == "turn_off" for a in acts)


def test_bat_het_khong_doan():
    assert parse_command_locally("bật tất cả", HOME) == []


# =========================================================
# Unit: connector không gửi lệnh khi không chắc chắn
# =========================================================
class _DeadTuya:
    """Tuya Cloud lỗi: không tra được loại thiết bị."""
    def __init__(self):
        self.posted = []

    def connect(self):
        return {"success": True}

    def get(self, path, *a):
        return {"success": False, "msg": "network"}

    def post(self, path, body):
        self.posted.append(body)
        return {"success": True}


def test_tuya_khong_ro_loai_thi_khong_gui_lenh():
    c = TuyaConnector()
    c.is_connected = True
    c.openapi = _DeadTuya()
    assert asyncio.run(c.turn_on("pump")) is False
    assert asyncio.run(c.set_mode("pump", "open")) is False
    assert c.openapi.posted == []
    assert asyncio.run(c.get_device_state("pump"))["status"] == "offline"


def test_rojeco_tat_khong_bao_thanh_cong_gia_va_chan_so_phan_vo_ly():
    c = RojecoConnector()
    c.is_connected = True
    posted = []
    c.openapi = D(connect=lambda: {"success": True},
                  post=lambda path, body: posted.append(body) or {"success": True})
    assert asyncio.run(c.turn_off("feed")) is False
    assert asyncio.run(c.set_mode("feed", "40")) is False
    assert posted == []
