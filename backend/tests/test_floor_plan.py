"""Sơ đồ mặt bằng 2D: GET/PUT /api/floor-plan + services/floor_plan.

Fixture `api` (conftest): khu A = lamp-a + door-a, khu B = lamp-b.
kid1/guest1 chỉ được cấp khu A. Không test nào gửi lệnh tới thiết bị thật.
"""
import copy

import pytest
from sqlalchemy import create_engine, inspect, text

from conftest import _req
from app.core.database import init_db
from app.models.member import MemberModel
from app.services import floor_plan as fp


def _owner(api, uid="owner1"):
    api.db.add(MemberModel(user_id=uid, email=f"{uid}@x.test", display_name=uid,
                           role="owner", status="active"))
    api.db.commit()
    return uid


def _layout(**over):
    base = {
        "rooms": [
            {"id": "main", "name": "Phòng chính", "width": 4.09, "depth": 3.0, "x": 0, "y": 0},
            {"id": "bath", "name": "Phòng tắm", "width": 2.17, "depth": 3.06, "x": 4.09, "y": 0},
        ],
        "doors": [{"id": "d1", "room": "main", "wall": "bottom", "offset": 1.0, "width": 0.9}],
        "devices": [
            {"device_id": "door-a", "room": "main", "x": 2.0, "y": 2.9},
            {"device_id": "lamp-a", "room": "main", "x": 1.0, "y": 1.0},
            {"device_id": "lamp-b", "room": "bath", "x": 1.0, "y": 1.5},
        ],
    }
    base.update(over)
    return base


def _get(api, user):
    r = _req(api.as_user(user), "GET", "/api/floor-plan")
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _put(api, user, body):
    return _req(api.as_user(user), "PUT", "/api/floor-plan", json=body)


# ---------------------------------------------------------------- mặc định
def test_chua_cau_hinh_tra_bo_cuc_mac_dinh_dung_kich_thuoc_that(api):
    _owner(api)
    data = _get(api, "owner1")
    assert data["configured"] is False
    rooms = {r["id"]: r for r in data["rooms"]}
    assert (rooms["main"]["width"], rooms["main"]["depth"]) == (4.09, 3.00)
    assert (rooms["bath"]["width"], rooms["bath"]["depth"]) == (2.17, 3.06)
    # Không tự đoán cửa / vị trí thiết bị.
    assert data["doors"] == [] and data["devices"] == []


def test_default_layout_la_ban_sao(api):
    a = fp.default_layout()
    a["rooms"].clear()
    assert fp.default_layout()["rooms"], "sửa bản trả về không được làm hỏng mặc định"


# ---------------------------------------------------------------- lưu / đọc
def test_chu_nha_luu_va_doc_lai(api):
    _owner(api)
    r = _put(api, "owner1", _layout())
    assert r.status_code == 200, r.text
    data = _get(api, "owner1")
    assert data["configured"] is True
    assert data["updated_at_ms"] > 0
    assert [d["device_id"] for d in data["devices"]] == ["door-a", "lamp-a", "lamp-b"]
    assert data["doors"][0] == {"id": "d1", "room": "main", "wall": "bottom", "offset": 1.0, "width": 0.9}


def test_kid_chi_thay_vi_tri_thiet_bi_trong_khu_minh(api):
    _owner(api)
    _put(api, "owner1", _layout())
    data = _get(api, "kid1")
    assert {d["device_id"] for d in data["devices"]} == {"door-a", "lamp-a"}
    # Phòng/cửa là của cả nhà — ai cũng thấy.
    assert len(data["rooms"]) == 2 and len(data["doors"]) == 1


@pytest.mark.parametrize("user,role", [("adult1", "adult"), ("kid1", None), ("guest1", None)])
def test_khong_phai_chu_nha_khong_sua_duoc(api, user, role):
    if role:
        api.db.add(MemberModel(user_id=user, email=f"{user}@x.test", display_name=user,
                               role=role, status="active"))
        api.db.commit()
    r = _put(api, user, _layout())
    assert r.status_code == 403


def test_pending_khong_doc_duoc(api):
    # Người lạ tự provision thành guest/pending.
    r = _req(api.as_user("stranger"), "GET", "/api/floor-plan")
    assert r.status_code == 403


def test_thiet_bi_da_xoa_tu_bien_mat_luc_doc(api):
    _owner(api)
    _put(api, "owner1", _layout())
    api.db.execute(text("DELETE FROM devices WHERE id = 'lamp-b'"))
    api.db.commit()
    assert "lamp-b" not in {d["device_id"] for d in _get(api, "owner1")["devices"]}


def test_luu_lai_khong_lam_mat_vi_tri_khac(api):
    _owner(api)
    _put(api, "owner1", _layout())
    body = _layout()
    body["devices"][0]["x"] = 3.5
    _put(api, "owner1", body)
    data = _get(api, "owner1")
    assert data["devices"][0]["x"] == 3.5
    assert len(data["devices"]) == 3


def test_layout_hong_trong_db_khong_lam_hong_api(api):
    _owner(api)
    _put(api, "owner1", _layout())
    api.db.execute(text("UPDATE floor_plans SET layout = 'không phải json'"))
    api.db.commit()
    data = _get(api, "owner1")
    assert data["rooms"][0]["width"] == 4.09  # về mặc định


# ---------------------------------------------------------------- làm sạch
KNOWN = {"door-a", "lamp-a", "lamp-b"}


def test_bo_thiet_bi_la_va_trung_kep_toa_do_vao_phong():
    body = _layout(devices=[
        {"device_id": "ghost", "room": "main", "x": 1, "y": 1},
        {"device_id": "lamp-a", "room": "main", "x": 9.0, "y": -0.5},
        {"device_id": "lamp-a", "room": "bath", "x": 1, "y": 1},
    ])
    out = fp.sanitize_layout(body, KNOWN)
    assert out["devices"] == [{"device_id": "lamp-a", "room": "main", "x": 4.09, "y": 0.0}]


@pytest.mark.parametrize("mutate,msg", [
    (lambda b: b.update(rooms=[]), "ít nhất 1 phòng"),
    (lambda b: b["rooms"][1].update(id="main"), "Trùng mã phòng"),
    (lambda b: b["rooms"][0].update(width=0.1), "Chiều rộng"),
    (lambda b: b["rooms"][0].update(width="4"), "phải là số"),
    (lambda b: b["rooms"][0].update(width=True), "phải là số"),
    (lambda b: b["rooms"][0].update(depth=float("nan")), "Chiều dài"),
    (lambda b: b["rooms"][0].update(name="  "), "Tên phòng"),
    (lambda b: b["doors"][0].update(wall="ceiling"), "Tường"),
    (lambda b: b["doors"][0].update(room="kitchen"), "phòng không tồn tại"),
    (lambda b: b["doors"][0].update(offset=3.5), "Cửa vượt quá|Vị trí cửa"),
    (lambda b: b["devices"][0].update(room="kitchen"), "phòng không tồn tại"),
    (lambda b: b.update(devices="abc"), "danh sách"),
])
def test_hinh_hoc_sai_bi_tu_choi(mutate, msg):
    body = copy.deepcopy(_layout())
    mutate(body)
    with pytest.raises(ValueError, match=msg):
        fp.sanitize_layout(body, KNOWN)


def test_cua_vua_khit_tuong_hop_le():
    body = _layout(doors=[{"id": "d", "room": "main", "wall": "left", "offset": 2.1, "width": 0.9}])
    assert fp.sanitize_layout(body, KNOWN)["doors"][0]["offset"] == 2.1


def test_put_hinh_hoc_sai_tra_400_khong_ghi(api):
    _owner(api)
    _put(api, "owner1", _layout())
    bad = _layout()
    bad["rooms"][0]["width"] = -1
    r = _put(api, "owner1", bad)
    assert r.status_code == 400
    assert "Chiều rộng" in r.json()["detail"]
    assert _get(api, "owner1")["rooms"][0]["width"] == 4.09  # bản cũ còn nguyên


def test_put_body_khong_phai_object_tra_loi_ro(api):
    _owner(api)
    r = _put(api, "owner1", ["rooms"])
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------- DB
def test_db_cu_chua_co_bang_duoc_tao_khi_boot_khong_mat_du_lieu(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    init_db(engine)
    with engine.begin() as c:
        c.execute(text("DROP TABLE floor_plans"))
        c.execute(text("INSERT INTO zones (name, sort_order, is_shared) VALUES ('Bếp', 5, 0)"))
    init_db(engine)  # boot lại trên DB "cũ"
    assert "floor_plans" in inspect(engine).get_table_names()
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM zones WHERE name = 'Bếp'")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM devices")).scalar() == 3
