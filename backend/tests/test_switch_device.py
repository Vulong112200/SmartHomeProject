"""Máy bơm tăng áp (công tắc Tuya) sống chung với cửa cuốn (cũng Tuya).

Hai bẫy được ghim ở đây:
  - parser chọn thiết bị theo HÃNG -> "đóng cửa" có thể rơi vào máy bơm;
  - từ khóa máy cho ăn "ăn" khớp vào "tăng áp" -> "bật máy bơm" cho mèo ăn.
"""
import asyncio
import time
from types import SimpleNamespace as D

from app.models.device import device_kind
from app.services.local_parser import parse_command_locally
from app.services.tuya_connector import TuyaConnector

PUMP = D(id="a3b71521047bba78aepet5", name="Máy bơm tăng áp", brand="tuya", category="switch")
DOOR = D(id="a32aae46a67dbe52860pza", name="Cửa cuốn", brand="tuya", category=None)
FEEDER = D(id="a32e6ab42d076b8bb5bbrh", name="Máy cho mèo ăn tự động", brand="rojeco", category=None)
PURIFIER = D(id="vsaq325492d4dce9e0f8eb348bb3be41", name="Lọc không khí", brand="vesync", category=None)
# Máy bơm đứng TRƯỚC cửa: lấy "Tuya đầu tiên" là trúng máy bơm.
HOME = [PUMP, DOOR, FEEDER, PURIFIER]


# ---------------------------------------------------------------- device_kind
def test_device_kind_category_thang_ten():
    assert device_kind(D(name="Cửa hàng", brand="tuya", category="switch")) == "switch"


def test_device_kind_tang_ap_khong_phai_may_cho_an():
    assert device_kind(D(name="Tăng áp (Home)", brand="tuya", category=None)) == "switch"


def test_device_kind_fallback_theo_hang():
    assert device_kind(D(name="Thiết bị A", brand="vesync", category=None)) == "purifier"
    assert device_kind(D(name="Thiết bị B", brand="lạ", category=None)) is None


# ---------------------------------------------------------------- parser
def test_bat_may_bom_khong_cho_meo_an():
    acts = parse_command_locally("bật máy bơm tăng áp", HOME)
    assert acts == [{"brand": "tuya", "id": PUMP.id, "action": "turn_on", "mode": None}]


def test_tat_may_bom():
    acts = parse_command_locally("tắt máy bơm", HOME)
    assert acts == [{"brand": "tuya", "id": PUMP.id, "action": "turn_off", "mode": None}]


def test_dong_cua_khong_roi_vao_may_bom():
    acts = parse_command_locally("đóng cửa cuốn", HOME)
    assert acts == [{"brand": "tuya", "id": DOOR.id, "action": "set_mode", "mode": "close"}]


def test_cho_meo_an_van_chay():
    acts = parse_command_locally("cho mèo ăn 2 phần", HOME)
    assert acts == [{"brand": "rojeco", "id": FEEDER.id, "action": "set_mode", "mode": "2"}]


def test_hen_khoang_may_bom_mac_dinh_tat_khi_ket_thuc():
    [r] = parse_command_locally("từ 6 giờ đến 6 giờ 30 bật máy bơm", HOME)
    assert r["intent"] == "schedule" and r["id"] == PUMP.id
    assert (r["action"], r["end_action"]) == ("turn_on", "turn_off")
    assert (r["time"], r["end_time"]) == ("06:00", "06:30")


# ---------------------------------------------------------------- connector
class _StubApi:
    def __init__(self, category, online=True, switch_1=False, control="stop", control_age_s=600):
        self.category, self.online, self.switch_1 = category, online, switch_1
        self.control = control
        self.control_ms = int((time.time() - control_age_s) * 1000)
        self.posted = []

    def connect(self):
        return {"success": True}

    def get(self, path):
        if path.startswith("/v1.0/devices/"):
            return {"success": True, "result": {
                "category": self.category, "online": self.online,
                "status": [{"code": "switch_1", "value": self.switch_1}],
            }}
        if path.endswith("/shadow/properties"):
            return {"success": True, "result": {"properties": [
                {"code": "control", "value": self.control, "time": self.control_ms},
            ]}}
        raise AssertionError(f"path không mong đợi: {path}")

    def post(self, path, body):
        self.posted.append(body["commands"])
        return {"success": True}


def _tuya(api):
    c = TuyaConnector()
    c.is_connected = True
    c.openapi = api
    return c


def test_cong_tac_doc_trang_thai_switch_1():
    assert asyncio.run(_tuya(_StubApi("tdq", switch_1=True)).get_device_state(PUMP.id))["status"] == "ON"
    assert asyncio.run(_tuya(_StubApi("tdq", switch_1=False)).get_device_state(PUMP.id))["status"] == "OFF"
    assert asyncio.run(_tuya(_StubApi("tdq", online=False)).get_device_state(PUMP.id))["status"] == "offline"


def test_cong_tac_bat_tat_gui_switch_1_khong_gui_control():
    api = _StubApi("tdq")
    c = _tuya(api)
    assert asyncio.run(c.turn_on(PUMP.id)) is True
    assert asyncio.run(c.turn_off(PUMP.id)) is True
    assert api.posted == [[{"code": "switch_1", "value": True}], [{"code": "switch_1", "value": False}]]


def test_cong_tac_tu_choi_mode_cua():
    api = _StubApi("tdq")
    assert asyncio.run(_tuya(api).set_mode(PUMP.id, "open")) is False
    assert api.posted == []


def test_cua_cuon_van_gui_control_nhu_cu():
    api = _StubApi("clkg")
    c = _tuya(api)
    assert asyncio.run(c.turn_off(DOOR.id)) is True
    assert api.posted[-1] == [{"code": "control", "value": "close"}]
    assert api.posted[0] == [{"code": "control", "value": "stop"}]  # interlock giữ nguyên


def _door_state(control, age_s):
    api = _StubApi("clkg", control=control, control_age_s=age_s)
    return asyncio.run(_tuya(api).get_device_state(DOOR.id))["door_state"]


def test_cua_vua_nhan_lenh_thi_dang_chay():
    assert _door_state("open", 5) == "opening"
    assert _door_state("close", 5) == "closing"


def test_cua_lenh_cu_thi_da_toi_noi_khong_ket_dang_chay():
    # Bấm công tắc tường Tuya: cloud chỉ ghi lệnh cuối, không có vị trí thật.
    assert _door_state("open", 120) == "open"
    assert _door_state("close", 120) == "closed"
    assert _door_state("stop", 120) == "stopped"
