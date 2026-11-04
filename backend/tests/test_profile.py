"""PATCH /api/me — hồ sơ của CHÍNH MÌNH (tên hiển thị, màu avatar)."""
import pytest

from conftest import _req
from app.models.member import MemberModel


def _me(api, user, **body):
    return _req(api.as_user(user), "PATCH", "/api/me", json=body)


def test_doi_ten_va_mau_cua_chinh_minh(api):
    r = _me(api, "kid1", display_name="  Bé Na  ", avatar_color="#FF8800")
    assert r.status_code == 200
    data = r.json()["data"]
    assert (data["display_name"], data["avatar_color"]) == ("Bé Na", "#FF8800")
    # /api/me đọc lại thấy giá trị mới
    me = _req(api.as_user("kid1"), "GET", "/api/me").json()["data"]
    assert me["avatar_color"] == "#FF8800"


def test_khong_tu_nang_vai_qua_api_me(api):
    # Trường role/status không có trong body hợp lệ -> bị bỏ qua, vai giữ nguyên.
    r = _me(api, "kid1", role="owner", status="active", display_name="Kid")
    assert r.status_code == 200
    api.db.expire_all()
    assert api.db.get(MemberModel, "kid1").role == "kid"


@pytest.mark.parametrize("body", [
    {"display_name": "   "},
    {"display_name": "x" * 41},
    {"avatar_color": "red"},
    {"avatar_color": "#12345"},
])
def test_gia_tri_sai_bi_tu_choi(api, body):
    assert _me(api, "kid1", **body).status_code == 400


def test_mau_null_tuong_minh_ve_mau_tu_dong(api):
    _me(api, "kid1", avatar_color="#112233")
    r = _me(api, "kid1", avatar_color=None)
    assert r.json()["data"]["avatar_color"] is None


def test_nguoi_cho_duyet_dat_duoc_ten_that(api):
    # Người lạ đăng nhập lần đầu (pending) đặt tên để chủ nhà nhận ra.
    r = _me(api, "newbie", display_name="Cô Hoa")
    assert r.status_code == 200
    assert api.db.get(MemberModel, "newbie").status == "pending"


def test_nguoi_bi_chan_khong_sua_duoc(api):
    api.db.add(MemberModel(user_id="bad", email="bad@x.test", display_name="bad",
                           role="guest", status="blocked"))
    api.db.commit()
    assert _me(api, "bad", display_name="Hacker").status_code == 403
