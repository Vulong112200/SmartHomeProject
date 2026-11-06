"""Điều kiện kịch bản (services/scene_condition_engine.py + POST /api/scenes/{id}/run).
Mọi lệnh/đọc trạng thái đi qua bản giả — không chạm thiết bị thật."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as D
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from conftest import _req
from app.models.scene import SceneModel
from app.services import scene_condition_engine as eng

VN = ZoneInfo("Asia/Ho_Chi_Minh")
PUMP = D(id="pump", name="Máy bơm", brand="tuya", category="switch")
AIR = D(id="air", name="Máy lọc", brand="vesync", category="purifier")
DOOR = D(id="door", name="Cửa cuốn", brand="tuya", category="curtain")
FEEDER = D(id="feed", name="Máy cho ăn", brand="rojeco", category="feeder")
DEVICES = {d.id: d for d in (PUMP, AIR, DOOR)}


def _at(hh, mm, tz=VN):
    return datetime(2026, 11, 6, hh, mm, tzinfo=tz)


def _evaluate(conditions, states=None, now=None, visible=DEVICES, known=None, reads=None):
    states = states or {}

    async def read_state(device):
        if reads is not None:
            reads.append(device.id)
        value = states.get(device.id, {"status": "OFF"})
        if isinstance(value, Exception):
            raise value
        return value

    return asyncio.run(eng.evaluate_conditions(
        conditions, visible_devices=visible, known_ids=known or set(DEVICES) | {"other"},
        read_state=read_state, now=now or _at(23, 0),
    ))


def _time(start, end):
    return {"type": "time_range", "start": start, "end": end, "timezone": "Asia/Ho_Chi_Minh"}


def _dev(device_id, expected):
    return {"type": "device_state", "device_id": device_id, "expected_state": expected}


# =========================================================
# Khoảng thời gian
# =========================================================
@pytest.mark.parametrize("now,expected", [
    ((22, 0), True), ((23, 59), True), ((0, 0), True), ((5, 59), True),
    ((6, 0), False), ((12, 0), False), ((21, 59), False),
])
def test_khoang_qua_dem_22h_den_6h(now, expected):
    r = _evaluate({"operator": "AND", "items": [_time("22:00", "06:00")]}, now=_at(*now))
    assert (r["result"] == eng.PASSED) is expected


@pytest.mark.parametrize("now,expected", [((8, 0), True), ((16, 59), True), ((17, 0), False), ((7, 59), False)])
def test_khoang_trong_ngay_bat_dau_tinh_ket_thuc_khong_tinh(now, expected):
    r = _evaluate({"operator": "AND", "items": [_time("08:00", "17:00")]}, now=_at(*now))
    assert (r["result"] == eng.PASSED) is expected


def test_khong_phu_thuoc_mui_gio_may_chu():
    # 15:30 UTC = 22:30 giờ VN -> trong khoảng 22:00–06:00 dù máy chủ chạy UTC.
    now_utc = datetime(2026, 11, 6, 15, 30, tzinfo=timezone.utc)
    assert _evaluate({"operator": "AND", "items": [_time("22:00", "06:00")]}, now=now_utc)["result"] == eng.PASSED


def test_gio_bat_dau_trung_ket_thuc_bi_tu_choi_luc_luu():
    with pytest.raises(ValueError, match="khác nhau"):
        eng.normalize_conditions({"items": [_time("07:00", "07:00")]}, lambda i: DEVICES[i])
    # Dữ liệu lọt vào DB bằng đường khác -> unknown, không bao giờ passed.
    r = _evaluate({"operator": "AND", "items": [_time("07:00", "07:00")]})
    assert r["result"] == eng.UNKNOWN


@pytest.mark.parametrize("bad", ["24:00", "7h", "", None, "12:60"])
def test_gio_sai_dinh_dang(bad):
    with pytest.raises(ValueError):
        eng.normalize_conditions({"items": [_time(bad, "06:00")]}, lambda i: DEVICES[i])


# =========================================================
# Gộp AND / OR (ba giá trị)
# =========================================================
def test_and_tat_ca_dung_thi_dat():
    r = _evaluate({"operator": "AND", "items": [_time("22:00", "06:00"), _dev("pump", "off")]})
    assert r["result"] == eng.PASSED
    assert [i["result"] for i in r["items"]] == ["passed", "passed"]


def test_and_mot_dieu_kien_sai_thi_failed_kem_ly_do():
    r = _evaluate({"operator": "AND", "items": [_time("22:00", "06:00"), _dev("pump", "off")]},
                  states={"pump": {"status": "ON"}})
    assert r["result"] == eng.FAILED
    assert "Máy bơm đang bật (cần đang tắt)" in r["reason"]


def test_or_mot_dieu_kien_dung_thi_dat():
    r = _evaluate({"operator": "OR", "items": [_time("08:00", "17:00"), _dev("pump", "off")]})
    assert r["result"] == eng.PASSED


def test_or_tat_ca_sai_thi_failed():
    r = _evaluate({"operator": "OR", "items": [_time("08:00", "17:00"), _dev("pump", "on")]})
    assert r["result"] == eng.FAILED


def test_and_sai_gio_thi_khong_doc_thiet_bi():
    reads = []
    r = _evaluate({"operator": "AND", "items": [_time("08:00", "17:00"), _dev("pump", "off")]}, reads=reads)
    assert r["result"] == eng.FAILED and reads == []
    assert r["items"][1]["result"] == eng.NOT_EVALUATED


def test_khong_co_dieu_kien_thi_dat():
    assert _evaluate(None)["result"] == eng.PASSED
    assert _evaluate({"operator": "AND", "items": []})["result"] == eng.PASSED


# =========================================================
# Trạng thái thiết bị: offline / lỗi / không quyền KHÔNG BAO GIỜ thành đạt
# =========================================================
def test_offline_khong_bi_coi_la_tat():
    r = _evaluate({"operator": "AND", "items": [_dev("pump", "off")]}, states={"pump": {"status": "offline"}})
    assert r["result"] == eng.UNKNOWN
    assert "offline" in r["reason"]


def test_or_sai_cong_offline_la_unknown_khong_phai_dat():
    r = _evaluate({"operator": "OR", "items": [_time("08:00", "17:00"), _dev("pump", "off")]},
                  states={"pump": {"status": "offline"}})
    assert r["result"] == eng.UNKNOWN


def test_and_dung_cong_offline_la_unknown():
    r = _evaluate({"operator": "AND", "items": [_time("22:00", "06:00"), _dev("pump", "off")]},
                  states={"pump": {"status": "offline"}})
    assert r["result"] == eng.UNKNOWN


def test_loi_doc_trang_thai_va_qua_thoi_gian_la_unknown(monkeypatch):
    r = _evaluate({"operator": "AND", "items": [_dev("pump", "off")]}, states={"pump": RuntimeError("cloud")})
    assert r["result"] == eng.UNKNOWN

    monkeypatch.setattr(eng, "STATE_READ_TIMEOUT", 0.01)

    async def slow(device):
        await asyncio.sleep(1)
        return {"status": "OFF"}

    r = asyncio.run(eng.evaluate_conditions({"operator": "AND", "items": [_dev("pump", "off")]},
                                            visible_devices=DEVICES, known_ids=set(DEVICES), read_state=slow))
    assert r["result"] == eng.UNKNOWN and "quá thời gian" in r["reason"]


def test_trang_thai_la_khong_xac_dinh():
    r = _evaluate({"operator": "AND", "items": [_dev("air", "on")]}, states={"air": {"status": "?"}})
    assert r["result"] == eng.UNKNOWN


@pytest.mark.parametrize("door_state,expected", [
    ("closed", eng.PASSED), ("open", eng.FAILED), ("partial", eng.FAILED),
    ("closing", eng.UNKNOWN), ("opening", eng.UNKNOWN), ("stopped", eng.UNKNOWN), ("unknown", eng.UNKNOWN),
])
def test_cua_cuon_phai_dong(door_state, expected):
    r = _evaluate({"operator": "AND", "items": [_dev("door", "closed")]},
                  states={"door": {"status": "OFF", "door_state": door_state}})
    assert r["result"] == expected


def test_thiet_bi_ngoai_quyen_khong_duoc_doc_va_khong_dat():
    reads = []
    visible = {"pump": PUMP}
    r = _evaluate({"operator": "OR", "items": [_dev("air", "off")]}, visible=visible, reads=reads)
    assert r["result"] == eng.UNKNOWN and reads == []
    assert "không có quyền" in r["reason"]


def test_thiet_bi_da_xoa_la_unknown():
    r = _evaluate({"operator": "AND", "items": [_dev("ghost", "off")]})
    assert r["result"] == eng.UNKNOWN and "không còn tồn tại" in r["reason"]


# =========================================================
# Chuẩn hóa lúc lưu
# =========================================================
def test_chuan_hoa_operator_va_mac_dinh_mui_gio():
    out = eng.normalize_conditions(
        {"operator": "or", "items": [{"type": "time_range", "start": "6:05", "end": "07:00", "x": 1}]},
        lambda i: DEVICES[i],
    )
    assert out == {"operator": "OR", "items": [
        {"type": "time_range", "start": "06:05", "end": "07:00", "timezone": "Asia/Ho_Chi_Minh"}]}


def test_list_tran_va_rong():
    assert eng.normalize_conditions([], lambda i: DEVICES[i]) is None
    assert eng.normalize_conditions(None, lambda i: DEVICES[i]) is None
    assert eng.normalize_conditions([_dev("pump", "OFF")], lambda i: DEVICES[i]) == {
        "operator": "AND", "items": [_dev("pump", "off")]}


@pytest.mark.parametrize("raw,msg", [
    ({"operator": "XOR", "items": [_dev("pump", "off")]}, "AND hoặc OR"),
    ({"items": [{"type": "weather"}]}, "không hỗ trợ"),
    ({"items": [_dev("pump", "open")]}, "trạng thái mong muốn"),
    ({"items": [_dev("door", "off")]}, "trạng thái mong muốn"),
    ({"items": [_dev("feed", "on")]}, "không dùng làm điều kiện"),
    ({"items": [_time("22:00", "06:00")] * 11}, "Tối đa"),
    ({"items": [{**_time("22:00", "06:00"), "timezone": "Mars/Base"}]}, "Múi giờ"),
    ("abc", "operator, items"),
])
def test_chuan_hoa_tu_choi(raw, msg):
    lookup = {**DEVICES, "feed": FEEDER}
    with pytest.raises(ValueError, match=msg):
        eng.normalize_conditions(raw, lambda i: lookup[i])


def test_load_stored():
    assert eng.load_stored(None) == (None, False)
    assert eng.load_stored('{"operator":"AND","items":[]}') == (None, False)
    assert eng.load_stored("{hỏng") == (None, True)
    assert eng.load_stored('[1,2]') == (None, True)


# =========================================================
# Qua HTTP (fixture `api`: lệnh bị ghi lại, không gửi thật)
# =========================================================
OWNER = dict(user_id="owner1", is_admin=True)


def _vn_window(offset_start_min, offset_end_min):
    now = datetime.now(VN)
    fmt = lambda m: (now + timedelta(minutes=m)).strftime("%H:%M")
    return _time(fmt(offset_start_min), fmt(offset_end_min))


INSIDE = lambda: _vn_window(-90, 90)     # chắc chắn chứa "bây giờ"
OUTSIDE = lambda: _vn_window(120, 240)   # chắc chắn không chứa


def _scene(conditions=None, actions=None, name="Đi ngủ"):
    body = {"name": name, "actions": actions or [
        {"device_id": "lamp-a", "action_type": "off"},
        {"device_id": "door-a", "action_type": "mode", "action_value": "close"},
    ]}
    if conditions is not None:
        body["conditions"] = conditions
    return body


def _create(api, body):
    return _req(api.as_user(**OWNER), "POST", "/api/scenes", json=body)


def _run(api, sid, user=OWNER):
    return _req(api.as_user(**user), "POST", f"/api/scenes/{sid}/run")


def _fake_states(monkeypatch, states):
    """Thay connector: trạng thái theo device_id, lệnh vẫn đi qua bản ghi giả của fixture."""
    import app.main as main
    reads = []

    class Fake:
        def __init__(self, brand):
            self.brand = brand

        async def get_device_state(self, device_id):
            reads.append(device_id)
            return states.get(device_id, {"device_id": device_id, "status": "OFF"})

    monkeypatch.setattr(main.device_manager, "get_connector", lambda brand: Fake(brand))
    return reads


def test_tao_kich_ban_co_dieu_kien_luu_dang_chuan_hoa(api):
    r = _create(api, _scene({"operator": "and", "items": [_time("22:00", "06:00"), _dev("lamp-b", "OFF")]}))
    assert r.status_code == 200
    assert r.json()["data"]["conditions"] == {"operator": "AND", "items": [
        _time("22:00", "06:00"), _dev("lamp-b", "off")]}


def test_kich_ban_cu_khong_dieu_kien_van_chay_binh_thuong(api):
    # Hàng cũ trong DB: cột conditions = NULL.
    api.db.add(SceneModel(name="Cũ", actions='[{"device_id": "lamp-a", "action_type": "off", "action_value": null}]'))
    api.db.commit()
    scenes = _req(api.as_user(**OWNER), "GET", "/api/scenes").json()["data"]
    assert scenes[0]["conditions"] == {"operator": "AND", "items": []}
    body = _run(api, scenes[0]["id"]).json()
    assert body["status"] == "success" and body["data"]["executed"] is True
    assert api.sent == [("tuya", "lamp-a", "off", None)]


def test_dieu_kien_khong_dat_thi_skipped_va_khong_gui_lenh_nao(api):
    sid = _create(api, _scene({"operator": "AND", "items": [OUTSIDE()]})).json()["data"]["id"]
    body = _run(api, sid).json()
    assert body["status"] == "skipped"
    assert body["message"] == "Kịch bản đã bỏ qua: Không thỏa mãn điều kiện thực thi."
    assert body["data"]["executed"] is False and body["data"]["conditions"]["result"] == "failed"
    assert api.sent == []


def test_dieu_kien_dat_thi_chay_tuan_tu_dung_thu_tu(api, monkeypatch):
    _fake_states(monkeypatch, {"lamp-b": {"status": "OFF"}})
    sid = _create(api, _scene({"operator": "AND", "items": [INSIDE(), _dev("lamp-b", "off")]})).json()["data"]["id"]
    body = _run(api, sid).json()
    assert body["status"] == "success" and body["data"]["conditions"]["result"] == "passed"
    assert api.sent == [("tuya", "lamp-a", "off", None), ("tuya", "door-a", "mode", "close")]


def test_or_mot_dung_thi_chay(api, monkeypatch):
    _fake_states(monkeypatch, {"lamp-b": {"status": "ON"}})
    sid = _create(api, _scene({"operator": "OR", "items": [OUTSIDE(), _dev("lamp-b", "on")]})).json()["data"]["id"]
    assert _run(api, sid).json()["status"] == "success"
    assert len(api.sent) == 2


def test_thiet_bi_dieu_kien_offline_thi_khong_chay(api, monkeypatch):
    _fake_states(monkeypatch, {"lamp-b": {"status": "offline"}})
    sid = _create(api, _scene({"operator": "AND", "items": [_dev("lamp-b", "off")]})).json()["data"]["id"]
    body = _run(api, sid).json()
    assert body["status"] == "skipped"
    assert body["message"] == "Kịch bản đã bỏ qua: Không xác định được điều kiện thực thi."
    assert api.sent == []


def test_doc_trang_thai_dieu_kien_bo_qua_cache(api, monkeypatch):
    import app.main as main
    main._cache_set("tuya", "lamp-b", {"status": "OFF"})  # cache cũ nói "tắt"
    reads = _fake_states(monkeypatch, {"lamp-b": {"status": "ON"}})  # thật ra đang bật
    sid = _create(api, _scene({"operator": "AND", "items": [_dev("lamp-b", "off")]})).json()["data"]["id"]
    assert _run(api, sid).json()["status"] == "skipped"
    assert reads == ["lamp-b"] and api.sent == []
    main._cache_invalidate("tuya", "lamp-b")


def test_kid_khong_muon_duoc_thiet_bi_ngoai_khu_de_qua_dieu_kien(api, monkeypatch):
    # lamp-b ở Phòng ngủ — kid1 chỉ được Phòng khách. OR với điều kiện "lamp-b tắt"
    # (đang tắt thật) KHÔNG được làm kịch bản chạy cho kid.
    reads = _fake_states(monkeypatch, {"lamp-b": {"status": "OFF"}})
    sid = _create(api, _scene({"operator": "OR", "items": [OUTSIDE(), _dev("lamp-b", "off")]})).json()["data"]["id"]
    body = _run(api, sid, dict(user_id="kid1")).json()
    assert body["status"] == "skipped" and api.sent == [] and reads == []
    assert "không có quyền" in body["data"]["conditions"]["reason"]


def test_luu_dieu_kien_tren_thiet_bi_khong_ton_tai_hoac_sai(api):
    assert _create(api, _scene({"items": [_dev("ghost", "off")]})).status_code == 404
    r = _create(api, _scene({"items": [_time("07:00", "07:00")]}))
    assert r.status_code == 400 and "khác nhau" in r.json()["detail"]
    assert _create(api, _scene({"items": [_dev("door-a", "off")]})).status_code == 400
    assert _create(api, _scene({"operator": "NAND", "items": [INSIDE()]})).status_code == 400


def test_patch_giu_nguyen_khi_khong_gui_va_xoa_khi_gui_null(api):
    sid = _create(api, _scene({"items": [OUTSIDE()]})).json()["data"]["id"]
    owner = lambda: api.as_user(**OWNER)
    r = _req(owner(), "PATCH", f"/api/scenes/{sid}", json={"name": "Đổi tên"}).json()["data"]
    assert len(r["conditions"]["items"]) == 1
    r = _req(owner(), "PATCH", f"/api/scenes/{sid}", json={"conditions": None}).json()["data"]
    assert r["conditions"] == {"operator": "AND", "items": []}
    api.db.expire_all()
    assert api.db.get(SceneModel, sid).conditions is None  # lưu NULL, giống kịch bản cũ
    assert _run(api, sid).json()["status"] == "success"


def test_dieu_kien_hong_trong_db_thi_khong_chay(api):
    api.db.add(SceneModel(name="Hỏng", conditions="{oops",
                          actions='[{"device_id": "lamp-a", "action_type": "off", "action_value": null}]'))
    api.db.commit()
    sid = api.db.query(SceneModel).filter_by(name="Hỏng").one().id
    body = _run(api, sid).json()
    assert body["status"] == "skipped" and api.sent == []


def test_giong_noi_cung_ton_trong_dieu_kien(api):
    _create(api, _scene({"items": [OUTSIDE()]}, name="Đi ngủ"))
    res = _req(api.as_user(**OWNER), "POST", "/api/ai/parse", json={"text": "đi ngủ"}).json()
    assert api.sent == []
    assert res["execution_results"][0]["success"] is False
    assert "Kịch bản đã bỏ qua" in res["execution_results"][0]["action"]


def test_kich_ban_mo_cua_van_bi_tu_choi_bang_giong_noi_du_dieu_kien_dat(api):
    _create(api, _scene({"items": [INSIDE()]}, name="Về nhà",
                        actions=[{"device_id": "door-a", "action_type": "mode", "action_value": "open"}]))
    res = _req(api.as_user(**OWNER), "POST", "/api/ai/parse", json={"text": "về nhà"}).json()
    assert api.sent == []
    assert "màn hình chính" in res["execution_results"][0]["action"]


def test_hanh_dong_ngoai_khu_van_bi_bo_qua_khi_dieu_kien_dat(api):
    sid = _create(api, _scene({"items": [INSIDE()]}, actions=[
        {"device_id": "door-a", "action_type": "mode", "action_value": "close"},
        {"device_id": "lamp-b", "action_type": "off"},
    ])).json()["data"]["id"]
    data = _run(api, sid, dict(user_id="kid1")).json()["data"]
    assert api.sent == [("tuya", "door-a", "mode", "close")] and data["skipped"] == 1
