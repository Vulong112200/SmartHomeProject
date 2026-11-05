"""Thứ tự thiết bị đồng bộ theo tài khoản: members.sort_order qua GET/PATCH /api/me.

Fixture `api` (conftest): khu A = lamp-a + door-a, khu B = lamp-b.
kid1/guest1 chỉ được cấp khu A. Người lạ (vd "owner1") tự provision guest/pending
nên test nào cần chủ nhà thì tạo hàng members trước.
"""
import pytest
from sqlalchemy import text

from conftest import _req
from app.models.device import DeviceModel
from app.models.member import MemberModel
from app.models.zone import MemberZoneAccessModel, ZoneModel


def _add_member(api, uid, role="adult", status="active", **kw):
    api.db.add(MemberModel(user_id=uid, email=f"{uid}@x.test", display_name=uid,
                           role=role, status=status, **kw))
    api.db.commit()


def _get_order(api, user):
    r = _req(api.as_user(user), "GET", "/api/me")
    assert r.status_code == 200
    return r.json()["data"]["sort_order"]


def _patch(api, user, **body):
    return _req(api.as_user(user), "PATCH", "/api/me", json=body)


def test_thanh_vien_cu_chua_sap_xep_tra_ve_rong(api):
    assert _get_order(api, "kid1") == []


def test_luu_va_doc_lai_dung_thu_tu(api):
    _add_member(api, "adult1")
    r = _patch(api, "adult1", sort_order=["door-a", "lamp-b", "lamp-a"])
    assert r.status_code == 200
    assert r.json()["data"]["sort_order"] == ["door-a", "lamp-b", "lamp-a"]
    assert _get_order(api, "adult1") == ["door-a", "lamp-b", "lamp-a"]


def test_chi_sua_sort_order_khong_dung_truong_ho_so_khac(api):
    _add_member(api, "adult1", avatar_color="#112233")
    _patch(api, "adult1", display_name="Mẹ")
    r = _patch(api, "adult1", sort_order=["lamp-a"])
    data = r.json()["data"]
    assert (data["display_name"], data["avatar_color"], data["role"], data["status"]) == (
        "Mẹ", "#112233", "adult", "active")
    # Ngược lại: sửa tên không xóa thứ tự đã lưu.
    _patch(api, "adult1", display_name="Mẹ Na")
    assert _get_order(api, "adult1") == ["lamp-a"]


def test_khu_trung_va_bo_id_khong_ton_tai(api):
    _add_member(api, "adult1")
    r = _patch(api, "adult1", sort_order=["lamp-a", "ghost", "lamp-a", "door-a", "ghost"])
    assert r.json()["data"]["sort_order"] == ["lamp-a", "door-a"]
    api.db.expire_all()
    assert api.db.get(MemberModel, "adult1").sort_order == ["lamp-a", "door-a"]


def test_khong_luu_duoc_thiet_bi_ngoai_quyen(api):
    # kid1 chỉ được khu A -> lamp-b (khu B) bị bỏ, không lưu vào DB.
    r = _patch(api, "kid1", sort_order=["lamp-b", "door-a", "lamp-a"])
    assert r.status_code == 200
    assert r.json()["data"]["sort_order"] == ["door-a", "lamp-a"]
    api.db.expire_all()
    assert api.db.get(MemberModel, "kid1").sort_order == ["door-a", "lamp-a"]


def test_moi_tai_khoan_co_thu_tu_rieng(api):
    _add_member(api, "a")
    _add_member(api, "b")
    _patch(api, "a", sort_order=["lamp-b", "lamp-a", "door-a"])
    _patch(api, "b", sort_order=["door-a", "lamp-a", "lamp-b"])
    assert _get_order(api, "a") == ["lamp-b", "lamp-a", "door-a"]
    assert _get_order(api, "b") == ["door-a", "lamp-a", "lamp-b"]


def test_thiet_bi_bi_xoa_bien_mat_khoi_thu_tu(api):
    _add_member(api, "adult1")
    _patch(api, "adult1", sort_order=["lamp-b", "lamp-a", "door-a"])
    api.db.delete(api.db.get(DeviceModel, "lamp-b"))
    api.db.commit()
    assert _get_order(api, "adult1") == ["lamp-a", "door-a"]


def test_mat_quyen_roi_duoc_cap_lai_thi_vi_tri_cu_quay_ve(api):
    zone_b = api.db.query(ZoneModel).filter_by(name="Phòng ngủ").one()
    api.db.add(MemberZoneAccessModel(user_id="kid1", zone_id=zone_b.id))
    api.db.commit()
    _patch(api, "kid1", sort_order=["lamp-b", "door-a", "lamp-a"])

    grant = api.db.get(MemberZoneAccessModel, ("kid1", zone_b.id))
    api.db.delete(grant)
    api.db.commit()
    assert _get_order(api, "kid1") == ["door-a", "lamp-a"]   # lọc lúc đọc, không lỗi

    api.db.add(MemberZoneAccessModel(user_id="kid1", zone_id=zone_b.id))
    api.db.commit()
    assert _get_order(api, "kid1") == ["lamp-b", "door-a", "lamp-a"]


@pytest.mark.parametrize("stored", ['"abc"', '{"x": 1}', '[1, null, "lamp-a"]', "123"])
def test_gia_tri_hong_trong_db_khong_lam_hong_api_me(api, stored):
    with api.db.bind.begin() as conn:
        conn.execute(text("UPDATE members SET sort_order = :v WHERE user_id = 'kid1'"), {"v": stored})
    api.db.expire_all()
    order = _get_order(api, "kid1")
    assert order == (["lamp-a"] if stored.startswith("[") else [])


def test_gia_tri_khong_phai_json_cung_khong_lam_hong_api_me(api):
    with api.db.bind.begin() as conn:
        conn.execute(text("UPDATE members SET sort_order = 'not json' WHERE user_id = 'kid1'"))
    api.db.expire_all()
    assert _get_order(api, "kid1") == []
    # Các API khác của người này không bị kéo theo (cột không nạp ở get_member).
    assert _req(api.as_user("kid1"), "GET", "/api/devices").status_code == 200
    # Lưu thứ tự mới ghi đè được giá trị hỏng.
    r = _patch(api, "kid1", sort_order=["lamp-a"])
    assert r.status_code == 200 and r.json()["data"]["sort_order"] == ["lamp-a"]


def test_null_tuong_minh_ve_thu_tu_mac_dinh(api):
    _patch(api, "kid1", sort_order=["door-a"])
    r = _patch(api, "kid1", sort_order=None)
    assert r.json()["data"]["sort_order"] == []
    api.db.expire_all()
    assert api.db.get(MemberModel, "kid1").sort_order is None


def test_danh_sach_qua_dai_bi_tu_choi(api):
    assert _patch(api, "kid1", sort_order=["x"] * 501).status_code == 400
    assert _patch(api, "kid1", sort_order=["x" * 129]).status_code == 400


def test_phan_tu_khong_phai_chuoi_bi_tu_choi(api):
    assert _patch(api, "kid1", sort_order=[1, 2]).status_code == 422
    assert _patch(api, "kid1", sort_order="lamp-a").status_code == 422


def test_nguoi_bi_chan_khong_luu_duoc(api):
    _add_member(api, "bad", role="guest", status="blocked")
    assert _patch(api, "bad", sort_order=["lamp-a"]).status_code == 403


def test_members_list_cua_chu_nha_khong_lo_sort_order(api):
    _add_member(api, "boss", role="owner")
    _patch(api, "kid1", sort_order=["door-a"])
    r = _req(api.as_user("boss"), "GET", "/api/members")
    assert r.status_code == 200
    assert all("sort_order" not in m for m in r.json()["data"])
