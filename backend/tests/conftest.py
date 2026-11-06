"""Fixture dùng chung cho test qua HTTP: chọn người đăng nhập, mọi lệnh tới
thiết bị bị ghi lại thay vì gửi thật (KHÔNG BAO GIỜ gọi connector thật)."""
import asyncio
import os
import tempfile
from types import SimpleNamespace as D

# CHỐT AN TOÀN — đặt TRƯỚC mọi import `app.*`: app.main gọi load_dotenv(), mà
# backend/.env của máy dev trỏ thẳng Supabase PRODUCTION. load_dotenv không ghi
# đè biến đã có ⇒ engine mặc định luôn là một SQLite tạm rỗng. Đường nào quên
# thay session trong test sẽ lỗi "no such table" thay vì ghi vào DB thật.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="smarthome-test-"), "default.db")

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import async_database_url, init_db, make_session_factory


def async_factory_for(path):
    """
    async_sessionmaker trên file SQLite `path` cho test. NullPool: mỗi test gọi
    asyncio.run (event loop MỚI) — kết nối aiosqlite giữ trong pool gắn với loop
    cũ, dùng lại sẽ treo/lỗi. Production chỉ có 1 loop nên dùng pool thường.
    """
    engine = create_async_engine(async_database_url(f"sqlite:///{path}"), poolclass=NullPool,
                                 connect_args={"timeout": 30})
    return make_session_factory(engine)


def run_async_db(path, fn):
    """`await fn(session)` trên một AsyncSession mới của file SQLite `path` (gọi thẳng code async)."""
    factory = async_factory_for(path)

    async def go():
        async with factory() as s:
            return await fn(s)
    return asyncio.run(go())
from app.models.device import DeviceModel
from app.models.member import MemberModel
from app.models.zone import MemberZoneAccessModel, ZoneModel


# =========================================================
# Fixture: app qua HTTP, chọn được người đăng nhập, mọi lệnh bị ghi lại
# =========================================================
@pytest.fixture(autouse=True)
def _clean_auth_env(monkeypatch):
    """Test không được phụ thuộc backend/.env của máy dev (app.main gọi load_dotenv
    lúc import): xóa các biến xác thực, test nào cần thì tự đặt."""
    for name in ("AUTH_DISABLED", "SUPABASE_URL", "SUPABASE_JWT_SECRET", "APP_TOKEN_SECRET", "ADMIN_EMAILS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "0")

    import app.main as main
    from app.core.auth import CurrentUser, get_current_user
    from app.core.database import get_db

    # Test chuẩn bị/kiểm dữ liệu bằng Session ĐỒNG BỘ; app chạy AsyncSession
    # (aiosqlite) trên CÙNG file SQLite.
    engine = create_engine(f"sqlite:///{tmp_path / 'sec.db'}")
    init_db(engine)
    Session = sessionmaker(bind=engine)
    async_factory = async_factory_for(tmp_path / "sec.db")

    async def _db():
        async with async_factory() as s:
            yield s

    sent = []

    async def _fake_execute(brand, device_id, action_type, action_value, invalidate_cache=None):
        sent.append((brand, device_id, action_type, action_value))
        return True

    ai_reply = {"actions": []}

    async def _fake_ai(text, devices):
        return ai_reply["actions"]

    class _FakeConnector:
        """Endpoint control/status gọi connector trực tiếp — cũng phải là giả."""
        def __init__(self, brand):
            self.brand = brand

        async def turn_on(self, device_id):
            sent.append((self.brand, device_id, "on", None))
            return True

        async def turn_off(self, device_id):
            sent.append((self.brand, device_id, "off", None))
            return True

        async def set_mode(self, device_id, mode):
            sent.append((self.brand, device_id, "mode", mode))
            return True

        async def get_device_state(self, device_id):
            return {"device_id": device_id, "status": "OFF"}

    monkeypatch.setattr(main, "execute_schedule_action", _fake_execute)
    monkeypatch.setattr(main, "parse_command_with_ai", _fake_ai)
    monkeypatch.setattr(main.device_manager, "get_connector", lambda brand: _FakeConnector(brand))
    # Session ngoài request (lịch sử lệnh, /ws, đồng bộ nhật ký) cũng phải về DB tạm.
    monkeypatch.setattr(main, "_realtime_session", async_factory)

    state = {}
    main.app.dependency_overrides[get_db] = _db
    main.app.dependency_overrides[get_current_user] = lambda: state["user"]

    setup = Session()
    zone_a = ZoneModel(name="Phòng khách", sort_order=1)
    zone_b = ZoneModel(name="Phòng ngủ", sort_order=2)
    setup.add_all([zone_a, zone_b])
    setup.commit()
    setup.add_all([
        DeviceModel(id="lamp-a", name="Đèn khách", brand="tuya", zone_id=zone_a.id, category="switch"),
        DeviceModel(id="lamp-b", name="Đèn ngủ", brand="tuya", zone_id=zone_b.id, category="switch"),
        DeviceModel(id="door-a", name="Cửa cuốn", brand="tuya", zone_id=zone_a.id, category="curtain"),
    ])
    for uid, role in (("kid1", "kid"), ("guest1", "guest")):
        setup.add(MemberModel(user_id=uid, email=f"{uid}@x.test", display_name=uid, role=role, status="active"))
    setup.commit()
    for uid in ("kid1", "guest1"):
        setup.add(MemberZoneAccessModel(user_id=uid, zone_id=zone_a.id))
    setup.commit()

    def as_user(user_id, is_admin=False):
        state["user"] = CurrentUser(user_id=user_id, email=f"{user_id}@x.test", is_admin=is_admin)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t")

    def call(fn):
        """`await fn(session)` trên AsyncSession của app (cùng file với `db`)."""
        return run_async_db(tmp_path / "sec.db", fn)

    yield D(as_user=as_user, db=setup, sent=sent, ai_reply=ai_reply, session=Session,
            call=call, async_session=async_factory)
    setup.close()
    main.app.dependency_overrides.clear()


def _req(client, method, path, **kw):
    async def go():
        async with client as c:
            return await c.request(method, path, **kw)
    return asyncio.run(go())


def _voice(api, user, text):
    return _req(api.as_user(user), "POST", "/api/ai/parse", json={"text": text}).json()


