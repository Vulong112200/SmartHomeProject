"""
Test phân quyền theo nhà (Phase 1b).

Chạy: cd backend && python -m pytest tests/test_household_scope.py -v
(phải là `python -m pytest` — tests/ không có __init__.py)

Test gọi thẳng các hàm trong core/household.py với Session thật trên SQLite
tạm, thay vì dựng cả app qua HTTP: nhanh hơn, và quyền vốn chỉ sống trong
household.py nên đó mới là thứ cần test. Vài test đi qua HTTP để chắc rằng
endpoint có GẮN dependency (quên gắn là lỗ hổng, mà unit test không bắt được).
"""
import asyncio

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import household
from app.core.auth import CurrentUser
from app.core.database import init_db
from app.models.device import DeviceModel
from app.models.member import MemberModel
from app.models.schedule import ScheduleModel
from app.models.zone import MemberZoneAccessModel, ZoneModel


# =========================================================
# Fixtures
# =========================================================
@pytest.fixture
def db(tmp_path):
    """Session trên DB tạm, đã có schema + khu 'Nhà' + 3 thiết bị seed."""
    engine = create_engine(f"sqlite:///{tmp_path / 'scope.db'}")
    init_db(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def zones(db):
    """Hai khu thật: A (Phòng khách) và B (Phòng ngủ). Seed 'Nhà' vẫn còn."""
    a = ZoneModel(name="Phòng khách", sort_order=1)
    b = ZoneModel(name="Phòng ngủ", sort_order=2)
    db.add_all([a, b])
    db.commit()
    return a, b


@pytest.fixture
def devices(db, zones):
    """Mỗi khu 1 thiết bị, cộng 1 thiết bị chưa phân khu (hộp thư đến)."""
    a, b = zones
    d_a = DeviceModel(id="dev-a", name="Đèn khách", brand="tuya", zone_id=a.id)
    d_b = DeviceModel(id="dev-b", name="Đèn ngủ", brand="tuya", zone_id=b.id)
    d_none = DeviceModel(id="dev-inbox", name="Ổ cắm mới", brand="tuya", zone_id=None)
    db.add_all([d_a, d_b, d_none])
    db.commit()
    return d_a, d_b, d_none


def _member(db, user_id, role, status="active", zone_ids=()):
    m = MemberModel(
        user_id=user_id, email=f"{user_id}@x.test", display_name=user_id,
        role=role, status=status,
    )
    db.add(m)
    db.commit()
    for zid in zone_ids:
        db.add(MemberZoneAccessModel(user_id=user_id, zone_id=zid))
    db.commit()
    return m


# =========================================================
# provision_member — người lạ đăng nhập lần đầu
# =========================================================
def test_nguoi_la_lan_dau_thanh_guest_pending(db):
    user = CurrentUser(user_id="u-new", email="la@x.test", is_admin=False)
    m = household.provision_member(db, user)
    assert m.role == "guest"
    assert m.status == "pending"


def test_email_trong_admin_emails_luon_la_owner(db):
    """Cứu hộ cấp env: chủ nhà không bao giờ tự khóa mình khỏi nhà mình."""
    user = CurrentUser(user_id="u-boss", email="boss@x.test", is_admin=True)
    m = household.provision_member(db, user)
    assert (m.role, m.status) == ("owner", "active")

    # Kể cả khi hàng đã bị hạ vai trong DB, lần đăng nhập sau phải nâng lại.
    m.role, m.status = "kid", "blocked"
    db.commit()
    again = household.provision_member(db, user)
    assert (again.role, again.status) == ("owner", "active")


def test_provision_khong_tao_trung_hang(db):
    user = CurrentUser(user_id="u-1", email="a@x.test", is_admin=False)
    household.provision_member(db, user)
    household.provision_member(db, user)
    assert db.query(MemberModel).filter(MemberModel.user_id == "u-1").count() == 1


# =========================================================
# Chặn pending / blocked
# =========================================================
def test_pending_bi_chan_o_moi_endpoint(db):
    m = _member(db, "u-pending", "guest", status="pending")
    with pytest.raises(HTTPException) as err:
        household.get_current_member(m)
    assert err.value.status_code == 403
    assert "chờ chủ nhà phê duyệt" in err.value.detail.lower()


def test_blocked_bi_chan_va_bao_khac_pending(db):
    m = _member(db, "u-blocked", "adult", status="blocked")
    with pytest.raises(HTTPException) as err:
        household.get_current_member(m)
    assert err.value.status_code == 403
    assert "bị chặn" in err.value.detail.lower()


def test_active_di_qua_duoc(db):
    m = _member(db, "u-ok", "adult")
    assert household.get_current_member(m) is m


# =========================================================
# device_query — phạm vi thiết bị
# =========================================================
def test_owner_thay_moi_thiet_bi_ke_ca_chua_phan_khu(db, devices):
    m = _member(db, "u-owner", "owner")
    ids = {d.id for d in household.device_query(db, m).all()}
    assert {"dev-a", "dev-b", "dev-inbox"} <= ids


def test_adult_cung_thay_moi_thiet_bi(db, devices):
    m = _member(db, "u-adult", "adult")
    ids = {d.id for d in household.device_query(db, m).all()}
    assert {"dev-a", "dev-b", "dev-inbox"} <= ids


def test_kid_chi_thay_khu_duoc_cap(db, zones, devices):
    a, _b = zones
    m = _member(db, "u-kid", "kid", zone_ids=[a.id])
    ids = {d.id for d in household.device_query(db, m).all()}
    assert ids == {"dev-a"}


def test_thiet_bi_chua_phan_khu_vo_hinh_voi_kid(db, zones, devices):
    """zone_id IS NULL là "hộp thư đến" — rơi ra miễn phí từ INNER JOIN."""
    a, b = zones
    m = _member(db, "u-kid2", "kid", zone_ids=[a.id, b.id])
    ids = {d.id for d in household.device_query(db, m).all()}
    assert "dev-inbox" not in ids


def test_kid_khong_duoc_cap_khu_nao_thi_khong_thay_gi(db, devices):
    m = _member(db, "u-kid3", "kid")
    assert household.device_query(db, m).all() == []


# =========================================================
# require_device_access — 403 vs 404
# =========================================================
def test_thiet_bi_ngoai_khu_tra_403_khong_phai_404(db, zones, devices):
    """Trong nhà không cần giấu nhau việc thiết bị đó tồn tại."""
    a, _b = zones
    m = _member(db, "u-kid4", "kid", zone_ids=[a.id])
    with pytest.raises(HTTPException) as err:
        household.require_device_access(db, m, "dev-b")
    assert err.value.status_code == 403


def test_thiet_bi_khong_ton_tai_tra_404(db, zones, devices):
    a, _b = zones
    m = _member(db, "u-kid5", "kid", zone_ids=[a.id])
    with pytest.raises(HTTPException) as err:
        household.require_device_access(db, m, "khong-co-that")
    assert err.value.status_code == 404


def test_thiet_bi_trong_khu_duoc_cap_thi_qua(db, zones, devices):
    a, _b = zones
    m = _member(db, "u-kid6", "kid", zone_ids=[a.id])
    assert household.require_device_access(db, m, "dev-a").id == "dev-a"


# =========================================================
# require_owner
# =========================================================
@pytest.mark.parametrize("role,allowed", [
    ("owner", True), ("adult", False), ("kid", False), ("guest", False),
])
def test_chi_owner_duoc_quan_tri(db, role, allowed):
    m = _member(db, f"u-{role}-adm", role)
    if allowed:
        assert household.require_owner(m) is m
    else:
        with pytest.raises(HTTPException) as err:
            household.require_owner(m)
        assert err.value.status_code == 403


# =========================================================
# Lịch hẹn
# =========================================================
def _schedule(db, device_id, created_by):
    s = ScheduleModel(
        brand="tuya", device_id=device_id, action_type="on",
        time="07:00", days="", enabled=True, created_by=created_by,
    )
    db.add(s)
    db.commit()
    return s


def test_lich_loc_theo_thiet_bi_khong_theo_nguoi_tao(db, zones, devices):
    """Lịch là của cả nhà: ai thấy thiết bị thì thấy lịch của nó."""
    a, b = zones
    s_a = _schedule(db, "dev-a", created_by="nguoi-khac")
    _schedule(db, "dev-b", created_by="nguoi-khac")

    kid = _member(db, "u-kid7", "kid", zone_ids=[a.id])
    seen = {s.id for s in household.schedule_query(db, kid).all()}
    assert seen == {s_a.id}


def test_guest_khong_duoc_tao_lich(db):
    m = _member(db, "u-guest", "guest")
    with pytest.raises(HTTPException) as err:
        household.require_can_schedule(m)
    assert err.value.status_code == 403


def test_kid_duoc_tao_lich(db):
    m = _member(db, "u-kid8", "kid")
    household.require_can_schedule(m)  # không raise là đạt


def test_kid_sua_duoc_lich_cua_chinh_minh(db, zones, devices):
    a, _b = zones
    kid = _member(db, "u-kid9", "kid", zone_ids=[a.id])
    s = _schedule(db, "dev-a", created_by="u-kid9")
    assert household.require_schedule_write(db, kid, s.id).id == s.id


def test_kid_khong_sua_duoc_lich_nguoi_khac(db, zones, devices):
    a, _b = zones
    kid = _member(db, "u-kid10", "kid", zone_ids=[a.id])
    s = _schedule(db, "dev-a", created_by="bo-me")
    with pytest.raises(HTTPException) as err:
        household.require_schedule_write(db, kid, s.id)
    assert err.value.status_code == 403
    assert "chính mình" in err.value.detail


def test_adult_sua_duoc_lich_nguoi_khac(db, zones, devices):
    adult = _member(db, "u-adult2", "adult")
    s = _schedule(db, "dev-a", created_by="ai-do")
    assert household.require_schedule_write(db, adult, s.id).id == s.id


def test_lich_ngoai_khu_tra_403(db, zones, devices):
    a, _b = zones
    kid = _member(db, "u-kid11", "kid", zone_ids=[a.id])
    s = _schedule(db, "dev-b", created_by="u-kid11")
    with pytest.raises(HTTPException) as err:
        household.require_schedule_write(db, kid, s.id)
    assert err.value.status_code == 403


# =========================================================
# Endpoint thật sự CÓ GẮN dependency (unit test không bắt được lỗi quên gắn)
# =========================================================
@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    App thật trên DB tạm, AUTH_DISABLED=1 (user giả là owner).

    Trỏ app vào DB tạm bằng dependency_overrides chứ KHÔNG reload module:
    reload tạo lại `Base`, mà app.models đã nằm trong sys.modules nên không
    đăng ký lại => metadata rỗng => create_all không tạo bảng nào.
    """
    monkeypatch.setenv("AUTH_DISABLED", "1")

    from app.core.database import get_db
    from app.main import app as fastapi_app

    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}")
    init_db(engine)
    TempSession = sessionmaker(bind=engine)

    def _override_get_db():
        session = TempSession()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    yield httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app), base_url="http://t"
    )
    fastapi_app.dependency_overrides.clear()


def _get(client, path):
    async def go():
        async with client as c:
            return await c.get(path)
    return asyncio.run(go())


def test_api_me_tra_vai_va_khu(client):
    r = _get(client, "/api/me")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["role"] == "owner"
    assert data["status"] == "active"
    assert data["can_admin"] is True


def test_health_van_public_khong_can_dang_nhap(client):
    """UptimeRobot ping /health — gắn nhầm auth vào đây là flatline giám sát."""
    r = _get(client, "/health")
    assert r.status_code == 200
    assert r.json()["status"] == "online"


@pytest.fixture
def client_as(tmp_path, monkeypatch):
    """
    Như `client` nhưng cho phép chọn ai đang đăng nhập, để kiểm rằng endpoint
    THẬT SỰ có gắn dependency phân quyền. Quên gắn `Depends(get_current_member)`
    vào một endpoint là lỗ hổng mà test gọi thẳng household.py không bắt được.
    """
    monkeypatch.setenv("AUTH_DISABLED", "0")

    from app.core.auth import CurrentUser as CU
    from app.core.auth import get_current_user
    from app.core.database import get_db
    from app.main import app as fastapi_app

    engine = create_engine(f"sqlite:///{tmp_path / 'api2.db'}")
    init_db(engine)
    TempSession = sessionmaker(bind=engine)

    def _override_get_db():
        session = TempSession()
        try:
            yield session
        finally:
            session.close()

    state = {"user": None}

    def _override_user():
        return state["user"]

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_current_user] = _override_user

    def _make(user_id, email, is_admin=False):
        state["user"] = CU(user_id=user_id, email=email, is_admin=is_admin)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fastapi_app), base_url="http://t"
        )

    setup = TempSession()
    yield _make, setup
    setup.close()
    fastapi_app.dependency_overrides.clear()


def test_kid_bi_403_khi_dieu_khien_thiet_bi_ngoai_khu(client_as):
    """Kiểm endpoint control có gắn require_device_access, không chỉ /api/devices."""
    make, db = client_as
    zone_a = ZoneModel(name="Phòng khách", sort_order=1)
    zone_b = ZoneModel(name="Phòng ngủ", sort_order=2)
    db.add_all([zone_a, zone_b])
    db.commit()
    db.add_all([
        DeviceModel(id="d-a", name="Đèn khách", brand="tuya", zone_id=zone_a.id),
        DeviceModel(id="d-b", name="Đèn ngủ", brand="tuya", zone_id=zone_b.id),
    ])
    db.add(MemberModel(user_id="kid1", email="kid@x.test", display_name="kid",
                       role="kid", status="active"))
    db.commit()
    db.add(MemberZoneAccessModel(user_id="kid1", zone_id=zone_a.id))
    db.commit()

    client = make("kid1", "kid@x.test")
    assert _get(client, "/api/test-control/tuya/d-b?action=on").status_code == 403

    # Danh sách thiết bị cũng chỉ có khu được cấp
    client = make("kid1", "kid@x.test")
    names = [d["id"] for d in _get(client, "/api/devices").json()["data"]]
    assert names == ["d-a"]


def test_pending_bi_403_o_api_devices_nhung_200_o_api_me(client_as):
    """Người lạ lần đầu: đăng nhập được, /api/me được, mọi thứ khác 403."""
    make, _db = client_as

    client = make("u-la", "la@x.test")
    me = _get(client, "/api/me")
    assert me.status_code == 200
    assert me.json()["data"]["status"] == "pending"

    client = make("u-la", "la@x.test")
    assert _get(client, "/api/devices").status_code == 403


def test_khong_co_token_thi_401(tmp_path, monkeypatch):
    """AUTH_DISABLED=0 và không gửi Bearer -> 401, không phải 200."""
    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")

    from app.core.database import get_db
    from app.main import app as fastapi_app

    engine = create_engine(f"sqlite:///{tmp_path / 'api3.db'}")
    init_db(engine)
    TempSession = sessionmaker(bind=engine)

    def _override_get_db():
        session = TempSession()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fastapi_app), base_url="http://t"
        )
        assert _get(client, "/api/devices").status_code == 401
    finally:
        fastapi_app.dependency_overrides.clear()


# =========================================================
# Quy tắc bật/tắt xác thực
# =========================================================
def test_thieu_secret_thi_xac_thuc_tu_tat(monkeypatch):
    """
    Service Render tạo tay KHÔNG đọc render.yaml. Nếu bật xác thực khi chưa có
    secret thì backend không verify nổi token -> 401 tất cả -> app cả nhà chết.
    """
    from app.core import auth
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    assert auth.auth_disabled() is True
    assert auth.auth_status() == (False, "thiếu SUPABASE_JWT_SECRET")


def test_co_secret_thi_xac_thuc_tu_bat(monkeypatch):
    from app.core import auth
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "s3cret")
    assert auth.auth_disabled() is False
    assert auth.auth_status()[0] is True


def test_auth_disabled_0_ep_bat_du_thieu_secret(monkeypatch):
    """Đặt tường minh thì thắng suy diễn — cho người vận hành muốn fail closed."""
    from app.core import auth
    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    assert auth.auth_disabled() is False


def test_auth_disabled_1_ep_tat_du_co_secret(monkeypatch):
    from app.core import auth
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "s3cret")
    assert auth.auth_disabled() is True
