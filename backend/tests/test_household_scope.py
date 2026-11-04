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
    assert auth.auth_status() == (False, "thiếu SUPABASE_URL / SUPABASE_JWT_SECRET")


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


# =========================================================
# app-token — đường sống của Home Widget / shortcut ở isolate nền
# =========================================================
def test_app_token_duoc_chap_nhan_nhu_dang_nhap(monkeypatch, tmp_path):
    """
    Isolate nền không có Supabase nên chỉ có app-token. Backend PHẢI nhận nó,
    nếu không Home Widget hiện "Không rõ" và nút bấm im lặng không làm gì.
    """
    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@x.test")

    from app.core.auth import issue_app_token
    from app.core.database import get_db
    from app.main import app as fastapi_app

    engine = create_engine(f"sqlite:///{tmp_path / 'tok.db'}")
    init_db(engine)
    TempSession = sessionmaker(bind=engine)

    def _override_get_db():
        s = TempSession()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        token = issue_app_token("u-boss", "boss@x.test")

        async def go():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=fastapi_app), base_url="http://t"
            ) as c:
                return await c.get(
                    "/api/devices", headers={"Authorization": f"Bearer {token}"}
                )

        r = asyncio.run(go())
        assert r.status_code == 200
    finally:
        fastapi_app.dependency_overrides.clear()


def test_app_token_ky_bang_secret_khac_bi_tu_choi(monkeypatch):
    """Thu hồi = đổi secret. Token cũ phải hết hiệu lực ngay."""
    from app.core import auth

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "secret-cu")
    token = auth.issue_app_token("u-1", "a@x.test")
    assert auth._decode_app_token(token) is not None

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "secret-moi")
    assert auth._decode_app_token(token) is None


def test_app_token_khong_nham_voi_token_supabase(monkeypatch):
    """app-token có `iss` riêng — token Supabase không được lọt qua đường này."""
    import jwt as pyjwt

    from app.core import auth

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "s")
    supabase_like = pyjwt.encode(
        {"sub": "u", "aud": "authenticated"}, "s", algorithm="HS256"
    )
    assert auth._decode_app_token(supabase_like) is None


# =========================================================
# Endpoint quản trị: khu vực + thành viên
# =========================================================
@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    """Client đăng nhập sẵn bằng chủ nhà, trên DB tạm."""
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@x.test")

    from app.core.database import get_db
    from app.main import app as fastapi_app

    engine = create_engine(f"sqlite:///{tmp_path / 'admin.db'}")
    init_db(engine)
    TempSession = sessionmaker(bind=engine)

    def _override_get_db():
        s = TempSession()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db

    def _client():
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fastapi_app), base_url="http://t"
        )

    setup = TempSession()
    yield _client, setup
    setup.close()
    fastapi_app.dependency_overrides.clear()


def _call(client_factory, method, path, **kw):
    async def go():
        async with client_factory() as c:
            return await c.request(method, path, **kw)
    return asyncio.run(go())


def test_tao_va_liet_ke_khu_vuc(owner_client):
    make, _db = owner_client
    r = _call(make, "POST", "/api/zones", json={"name": "Phòng ngủ", "sort_order": 1})
    assert r.status_code == 200
    r = _call(make, "GET", "/api/zones")
    names = [z["name"] for z in r.json()["data"]]
    assert "Phòng ngủ" in names
    assert "Nhà" in names  # khu seed mặc định


def test_ten_khu_rong_bi_tu_choi(owner_client):
    make, _db = owner_client
    r = _call(make, "POST", "/api/zones", json={"name": "   "})
    assert r.status_code == 400


def test_xoa_khu_thi_thiet_bi_ve_hop_thu_den_chu_khong_bi_xoa(owner_client):
    """Xóa thiết bị theo khu là mất luôn cả lịch hẹn của chúng."""
    make, db = owner_client
    zone_id = db.query(ZoneModel).first().id
    before = db.query(DeviceModel).count()

    r = _call(make, "DELETE", f"/api/zones/{zone_id}")
    assert r.status_code == 200

    db.expire_all()
    assert db.query(DeviceModel).count() == before      # không mất thiết bị nào
    assert all(d.zone_id is None for d in db.query(DeviceModel).all())


def test_gan_thiet_bi_vao_khu(owner_client):
    make, db = owner_client
    r = _call(make, "POST", "/api/zones", json={"name": "Bếp"})
    assert r.status_code == 200
    bep = db.query(ZoneModel).filter(ZoneModel.name == "Bếp").first()

    r = _call(make, "PATCH", "/api/devices/a32aae46a67dbe52860pza",
              json={"zone_id": bep.id})
    assert r.status_code == 200
    assert r.json()["data"]["zone_name"] == "Bếp"


def test_gan_vao_khu_khong_ton_tai_bi_tu_choi(owner_client):
    make, _db = owner_client
    r = _call(make, "PATCH", "/api/devices/a32aae46a67dbe52860pza",
              json={"zone_id": 9999})
    assert r.status_code == 400


def test_dat_va_bo_loai_thiet_bi(owner_client):
    make, _db = owner_client
    r = _call(make, "PATCH", "/api/devices/a32aae46a67dbe52860pza",
              json={"category": "feeder"})
    assert r.status_code == 200
    assert r.json()["data"]["category"] == "feeder"

    # null tường minh = bỏ loại, client quay về suy từ tên.
    r = _call(make, "PATCH", "/api/devices/a32aae46a67dbe52860pza",
              json={"category": None})
    assert r.status_code == 200
    assert r.json()["data"]["category"] is None


def test_loai_thiet_bi_khong_hop_le_bi_tu_choi(owner_client):
    make, _db = owner_client
    r = _call(make, "PATCH", "/api/devices/a32aae46a67dbe52860pza",
              json={"category": "toaster"})
    assert r.status_code == 400


def test_zone_id_null_tuong_minh_dua_ve_hop_thu_den(owner_client):
    make, db = owner_client
    r = _call(make, "PATCH", "/api/devices/a32aae46a67dbe52860pza",
              json={"zone_id": None})
    assert r.status_code == 200
    assert r.json()["data"]["zone_id"] is None


def test_duyet_thanh_vien_va_cap_khu(owner_client):
    make, db = owner_client
    db.add(MemberModel(user_id="kid9", email="kid9@x.test", display_name="Kid",
                       role="guest", status="pending"))
    db.commit()
    zone_id = db.query(ZoneModel).first().id

    r = _call(make, "PATCH", "/api/members/kid9",
              json={"role": "kid", "status": "active", "zone_ids": [zone_id]})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "active"
    assert data["zone_ids"] == [zone_id]


def test_zone_ids_thay_ca_bo_khong_phai_them_bot(owner_client):
    make, db = owner_client
    z1 = db.query(ZoneModel).first().id
    _call(make, "POST", "/api/zones", json={"name": "Kho"})
    z2 = db.query(ZoneModel).filter(ZoneModel.name == "Kho").first().id

    db.add(MemberModel(user_id="k2", email="k2@x.test", display_name="",
                       role="kid", status="active"))
    db.commit()

    _call(make, "PATCH", "/api/members/k2", json={"zone_ids": [z1, z2]})
    r = _call(make, "PATCH", "/api/members/k2", json={"zone_ids": [z2]})
    assert r.json()["data"]["zone_ids"] == [z2]  # z1 bị gỡ, không cộng dồn


def test_khong_the_tu_ha_vai_chinh_minh(owner_client):
    """Chặn ở API chứ không chỉ UI — app bản cũ vẫn gọi thẳng vào đây được."""
    make, _db = owner_client
    from app.core.auth import DEV_USER_ID

    _call(make, "GET", "/api/me")  # tạo hàng members cho user dev
    r = _call(make, "PATCH", f"/api/members/{DEV_USER_ID}", json={"role": "kid"})
    assert r.status_code == 400
    assert "chính mình" in r.json()["detail"]


def test_khong_the_tu_chan_chinh_minh(owner_client):
    make, _db = owner_client
    from app.core.auth import DEV_USER_ID

    _call(make, "GET", "/api/me")
    r = _call(make, "PATCH", f"/api/members/{DEV_USER_ID}", json={"status": "blocked"})
    assert r.status_code == 400


def test_nha_khong_bao_gio_mat_chu(owner_client):
    """
    Bất biến thật: sau mọi thao tác hợp lệ, nhà vẫn còn ít nhất 1 owner active.

    Hai chốt cộng lại đủ đảm bảo điều đó, và chốt "owner cuối cùng" trong
    update_member là BACKSTOP chứ không phải đường chạy chính: người đang thao
    tác bắt buộc đã là owner/active (qua require_owner), nên khi họ hạ vai một
    owner KHÁC thì luôn còn ít nhất 2 owner; còn tự hạ vai thì chốt "chính
    mình" bắt trước. Test này ghim bất biến, không ghim đường đi.
    """
    make, db = owner_client
    _call(make, "GET", "/api/me")  # user dev được tạo thành owner/active

    db.add(MemberModel(user_id="boss3", email="boss3@x.test", display_name="",
                       role="owner", status="active"))
    db.commit()

    # Hạ vai owner khác: cho phép, vì người thao tác vẫn là owner.
    r = _call(make, "PATCH", "/api/members/boss3", json={"role": "adult"})
    assert r.status_code == 200

    db.expire_all()
    remaining = db.query(MemberModel).filter(
        MemberModel.role == "owner", MemberModel.status == "active").count()
    assert remaining >= 1


def test_vai_khong_hop_le_bi_tu_choi(owner_client):
    make, db = owner_client
    db.add(MemberModel(user_id="k3", email="k3@x.test", display_name="",
                       role="kid", status="active"))
    db.commit()
    r = _call(make, "PATCH", "/api/members/k3", json={"role": "superadmin"})
    assert r.status_code == 400


def test_xoa_thiet_bi_xoa_luon_lich_cua_no(owner_client):
    """Lịch mồ côi sẽ bắn vào thiết bị không tồn tại mỗi ngày, mãi mãi."""
    make, db = owner_client
    db.add(ScheduleModel(brand="tuya", device_id="a32aae46a67dbe52860pza",
                         action_type="on", time="07:00", days="", enabled=True))
    db.commit()
    assert db.query(ScheduleModel).count() == 1

    r = _call(make, "DELETE", "/api/devices/a32aae46a67dbe52860pza")
    assert r.status_code == 200
    db.expire_all()
    assert db.query(ScheduleModel).count() == 0


def test_them_thiet_bi_trung_id_la_idempotent(owner_client):
    make, db = owner_client
    r = _call(make, "POST",
              "/api/devices?id=a32aae46a67dbe52860pza&name=X&brand=tuya")
    assert r.json()["status"] == "success"
    assert "đã có trong nhà" in r.json()["message"]
    assert db.query(DeviceModel).filter(
        DeviceModel.id == "a32aae46a67dbe52860pza").count() == 1
