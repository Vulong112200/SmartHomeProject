"""Fixture dùng chung cho test qua HTTP: chọn người đăng nhập, mọi lệnh tới
thiết bị bị ghi lại thay vì gửi thật (KHÔNG BAO GIỜ gọi connector thật)."""
import asyncio
from types import SimpleNamespace as D

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import init_db
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

    engine = create_engine(f"sqlite:///{tmp_path / 'sec.db'}")
    init_db(engine)
    Session = sessionmaker(bind=engine)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

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

    yield D(as_user=as_user, db=setup, sent=sent, ai_reply=ai_reply, session=Session)
    setup.close()
    main.app.dependency_overrides.clear()


def _req(client, method, path, **kw):
    async def go():
        async with client as c:
            return await c.request(method, path, **kw)
    return asyncio.run(go())


def _voice(api, user, text):
    return _req(api.as_user(user), "POST", "/api/ai/parse", json={"text": text}).json()


