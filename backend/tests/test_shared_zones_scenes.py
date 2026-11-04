"""Khu dùng chung cả nhà + kịch bản (đợt 2). Mọi lệnh đi qua bộ ghi giả."""
from conftest import _req
from app.models.device import DeviceModel
from app.models.zone import ZoneModel


def _ids(api, user, path="/api/devices"):
    return sorted(d["id"] for d in _req(api.as_user(user), "GET", path).json()["data"])


def _share_zone_b(api):
    zone_b = api.db.query(ZoneModel).filter(ZoneModel.name == "Phòng ngủ").one()
    r = _req(api.as_user("owner1", is_admin=True), "PATCH", f"/api/zones/{zone_b.id}", json={"is_shared": True})
    assert r.json()["data"]["is_shared"] is True
    return zone_b


# =========================================================
# Khu dùng chung
# =========================================================
def test_kid_thay_thiet_bi_khu_dung_chung_khong_can_cap(api):
    assert _ids(api, "kid1") == ["door-a", "lamp-a"]
    _share_zone_b(api)
    assert _ids(api, "kid1") == ["door-a", "lamp-a", "lamp-b"]
    assert _ids(api, "guest1") == ["door-a", "lamp-a", "lamp-b"]


def test_khu_dung_chung_hien_trong_api_me_va_dieu_khien_duoc(api):
    _share_zone_b(api)
    zones = _req(api.as_user("kid1"), "GET", "/api/me").json()["data"]["zones"]
    assert {z["name"]: z["is_shared"] for z in zones} == {"Phòng khách": False, "Phòng ngủ": True}
    r = _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/lamp-b?action=on")
    assert r.json()["status"] == "success"
    assert api.sent == [("tuya", "lamp-b", "on", None)]


def test_bo_dung_chung_thi_mat_quyen_ngay(api):
    zone_b = _share_zone_b(api)
    _req(api.as_user("owner1", is_admin=True), "PATCH", f"/api/zones/{zone_b.id}", json={"is_shared": False})
    assert _ids(api, "kid1") == ["door-a", "lamp-a"]
    assert _req(api.as_user("kid1"), "GET", "/api/test-control/tuya/lamp-b?action=on").status_code == 403


def test_thiet_bi_chua_phan_khu_van_vo_hinh_voi_kid(api):
    _share_zone_b(api)
    api.db.add(DeviceModel(id="inbox", name="Ổ mới", brand="tuya", zone_id=None))
    api.db.commit()
    assert "inbox" not in _ids(api, "kid1")


def test_api_devices_bao_khu_dung_chung(api):
    _share_zone_b(api)
    data = _req(api.as_user("kid1"), "GET", "/api/devices").json()["data"]
    assert {d["id"]: d["zone_shared"] for d in data}["lamp-b"] is True


# =========================================================
# Kịch bản
# =========================================================
LEAVE_HOME = {
    "name": "Ra khỏi nhà",
    "icon": "logout",
    "actions": [
        {"device_id": "door-a", "action_type": "mode", "action_value": "close"},
        {"device_id": "lamp-b", "action_type": "off"},
    ],
}


def _create(api, user="owner1", body=LEAVE_HOME, is_admin=True):
    return _req(api.as_user(user, is_admin=is_admin), "POST", "/api/scenes", json=body)


def test_chu_nha_tao_kich_ban_luu_dang_chuan_hoa(api):
    r = _create(api)
    assert r.status_code == 200
    actions = r.json()["data"]["actions"]
    assert actions == [
        {"device_id": "door-a", "action_type": "mode", "action_value": "close"},
        {"device_id": "lamp-b", "action_type": "off", "action_value": None},
    ]
    assert [s["name"] for s in _req(api.as_user("kid1"), "GET", "/api/scenes").json()["data"]] == ["Ra khỏi nhà"]


def test_kid_khong_tao_sua_xoa_duoc_kich_ban(api):
    assert _create(api, "kid1", is_admin=False).status_code == 403
    sid = _create(api).json()["data"]["id"]
    assert _req(api.as_user("kid1"), "PATCH", f"/api/scenes/{sid}", json={"name": "x"}).status_code == 403
    assert _req(api.as_user("kid1"), "DELETE", f"/api/scenes/{sid}").status_code == 403


def test_hanh_dong_sai_loai_bi_tu_choi_luc_tao(api):
    body = {"name": "Mở cửa sai", "actions": [{"device_id": "door-a", "action_type": "on"}]}
    assert _create(api, body=body).status_code == 400
    body = {"name": "Rỗng", "actions": []}
    assert _create(api, body=body).status_code == 400
    body = {"name": "Ma", "actions": [{"device_id": "khong-ton-tai", "action_type": "off"}]}
    assert _create(api, body=body).status_code == 404


def test_chay_kich_ban_tuan_tu_theo_dung_thu_tu(api):
    sid = _create(api).json()["data"]["id"]
    res = _req(api.as_user("owner1", is_admin=True), "POST", f"/api/scenes/{sid}/run").json()["data"]
    assert api.sent == [("tuya", "door-a", "mode", "close"), ("tuya", "lamp-b", "off", None)]
    assert res["skipped"] == 0 and all(r["success"] for r in res["results"])


def test_kid_chay_kich_ban_chi_phan_minh_dung_duoc(api):
    sid = _create(api).json()["data"]["id"]
    res = _req(api.as_user("kid1"), "POST", f"/api/scenes/{sid}/run").json()["data"]
    assert api.sent == [("tuya", "door-a", "mode", "close")]  # lamp-b ngoài khu -> bỏ qua
    assert res["skipped"] == 1


def test_thiet_bi_bi_xoa_sau_khi_tao_kich_ban_thi_bo_qua(api):
    sid = _create(api).json()["data"]["id"]
    _req(api.as_user("owner1", is_admin=True), "DELETE", "/api/devices/lamp-b")
    res = _req(api.as_user("owner1", is_admin=True), "POST", f"/api/scenes/{sid}/run").json()["data"]
    assert res["skipped"] == 1
    assert api.sent == [("tuya", "door-a", "mode", "close")]


def test_sua_kich_ban(api):
    sid = _create(api).json()["data"]["id"]
    r = _req(api.as_user("owner1", is_admin=True), "PATCH", f"/api/scenes/{sid}",
             json={"name": "Đi ngủ", "actions": [{"device_id": "lamp-a", "action_type": "off"}]})
    data = r.json()["data"]
    assert data["name"] == "Đi ngủ" and len(data["actions"]) == 1
    assert _req(api.as_user("owner1", is_admin=True), "PATCH", f"/api/scenes/{sid}",
                json={"name": "   "}).status_code == 400


def test_api_me_bao_quyen_sua_kich_ban(api):
    me = lambda u, a=False: _req(api.as_user(u, is_admin=a), "GET", "/api/me").json()["data"]
    assert me("owner1", True)["can_edit_scenes"] is True
    assert me("kid1")["can_edit_scenes"] is False
