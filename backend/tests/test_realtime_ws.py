"""
/ws — luồng thật qua endpoint: xác thực, lệnh (app / trợ lý / lịch) → sự kiện,
quyền theo khu, lệnh lỗi không phát, chặn thành viên → ngắt, app cũ chỉ echo.

Gọi thẳng ASGI app trong CÙNG event loop với HTTP (TestClient của starlette
0.27 không chạy với httpx 0.28). Mọi lần nhận có timeout: lỗi không bao giờ
làm treo bộ test. Connector luôn là bản giả — không gửi lệnh tới thiết bị thật.
"""
import asyncio
import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.member import MemberModel
from app.models.schedule import ScheduleModel
from app.services import realtime, scheduler
from app.services.realtime import ConnectionManager

LEGACY_ECHO = "📡 Server đã nhận lệnh, đang xử lý qua AI..."


class WsClosed(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class AsgiWS:
    """Client WebSocket tối giản nói chuyện thẳng với ASGI app."""

    def __init__(self, app, headers=()):
        self._in: asyncio.Queue = asyncio.Queue()
        self._out: asyncio.Queue = asyncio.Queue()
        scope = {
            "type": "websocket", "asgi": {"version": "3.0"}, "scheme": "ws",
            "path": "/ws", "raw_path": b"/ws", "root_path": "", "query_string": b"",
            "headers": [(k.encode(), v.encode()) for k, v in headers],
            "server": ("t", 80), "client": ("c", 1), "subprotocols": [],
        }
        self.task = asyncio.create_task(app(scope, self._in.get, self._out.put))

    async def connect(self):
        await self._in.put({"type": "websocket.connect"})
        msg = await asyncio.wait_for(self._out.get(), 5)
        if msg["type"] == "websocket.close":
            raise WsClosed(msg.get("code"))
        assert msg["type"] == "websocket.accept", msg
        return self

    async def send_text(self, text):
        await self._in.put({"type": "websocket.receive", "text": text})

    async def send_json(self, obj):
        await self.send_text(json.dumps(obj))

    async def receive_text(self, timeout=5.0):
        msg = await asyncio.wait_for(self._out.get(), timeout)
        if msg["type"] == "websocket.close":
            raise WsClosed(msg.get("code"))
        return msg["text"]

    async def receive_json(self, timeout=5.0):
        return json.loads(await self.receive_text(timeout))

    async def nothing_for(self, seconds):
        try:
            msg = await asyncio.wait_for(self._out.get(), seconds)
        except asyncio.TimeoutError:
            return True
        raise AssertionError(f"không được nhận gì, nhưng nhận {msg}")

    async def close(self):
        await self._in.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(self.task, 5)
        except Exception:
            pass


class _StatefulConnector:
    """Connector giả có trạng thái: lệnh đổi trạng thái, `fail` = thiết bị không nhận."""

    def __init__(self, sent, states, fail):
        self.sent, self.states, self.fail = sent, states, fail

    async def turn_on(self, device_id):
        return self._do(device_id, "ON")

    async def turn_off(self, device_id):
        return self._do(device_id, "OFF")

    async def set_mode(self, device_id, mode):
        return self._do(device_id, self.states.get(device_id, "OFF"))

    def _do(self, device_id, new_state):
        self.sent.append(device_id)
        if device_id in self.fail:
            return False
        self.states[device_id] = new_state
        return True

    async def get_device_state(self, device_id):
        return {"device_id": device_id, "status": self.states.get(device_id, "OFF")}


@pytest.fixture
def ws(api, monkeypatch):
    import app.main as main
    from app.core.auth import issue_app_token

    monkeypatch.setenv("APP_TOKEN_SECRET", "test-secret-for-ws-0123456789abcdef")
    # Token /ws đi đường xác thực THẬT: chủ nhà là nhờ ADMIN_EMAILS như production.
    monkeypatch.setenv("ADMIN_EMAILS", "owner@x.test")
    # /ws đọc DB ở thread riêng (asyncio.to_thread) -> engine cho phép đa luồng.
    engine = create_engine(api.db.get_bind().url, connect_args={"check_same_thread": False})
    monkeypatch.setattr(main, "_realtime_session", sessionmaker(bind=engine))
    monkeypatch.setattr(main, "db_ready", True)
    monkeypatch.setattr(main, "_status_cache", {})
    monkeypatch.setattr(realtime, "FOLLOWUP_DELAYS", (0.05,))

    mgr = ConnectionManager()
    mgr.configure(audience=main._ws_audience, refresh=main._ws_refresh, targets=main._ws_watch_targets)
    monkeypatch.setattr(realtime, "manager", mgr)

    states, fail, sent = {}, set(), []
    monkeypatch.setattr(main.device_manager, "get_connector",
                        lambda brand: _StatefulConnector(sent, states, fail))

    api.db.add(MemberModel(user_id="newbie", email="newbie@x.test", role="guest", status="pending"))
    api.db.commit()

    def token(uid):
        return issue_app_token(uid, f"{uid}@x.test")

    async def http(user, method, path, **kw):
        api.as_user(user, is_admin=(user == "owner"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            return await c.request(method, path, **kw)

    async def raw(headers=()):
        return await AsgiWS(main.app, headers=headers).connect()

    async def open_ws(uid):
        sock = await raw()
        await sock.send_json({"event": realtime.AUTH, "token": token(uid)})
        ready = await sock.receive_json()
        assert ready["event"] == realtime.READY and ready["data"]["user_id"] == uid
        return sock

    class Env:
        pass

    env = Env()
    env.http, env.raw, env.open_ws, env.token = http, raw, open_ws, token
    env.fail, env.states, env.mgr, env.db, env.ai_reply = fail, states, mgr, api.db, api.ai_reply
    yield env
    engine.dispose()


def _run(coro):
    return asyncio.run(coro)


async def _until(sock, pred, limit=20):
    """Đọc tới khi gặp message thỏa `pred`; trả mọi message đã đọc."""
    seen = []
    for _ in range(limit):
        msg = await sock.receive_json()
        seen.append(msg)
        if pred(msg):
            return seen
    raise AssertionError(f"không thấy message mong đợi trong {seen}")


def _is(event, device_id):
    return lambda m: m["event"] == event and m["device_id"] == device_id


# =========================================================
def test_lenh_tu_may_khac_toi_dung_nguoi_duoc_quyen(ws):
    async def go():
        kid = await ws.open_ws("kid1")
        owner = await ws.open_ws("owner")
        # Chủ nhà bật đèn khu B (kid1 KHÔNG được cấp) rồi đèn khu A.
        r = await ws.http("owner", "GET", "/api/test-control/tuya/lamp-b?action=on")
        assert r.json()["status"] == "success"
        r = await ws.http("owner", "GET", "/api/test-control/tuya/lamp-a?action=on")
        assert r.json()["status"] == "success"

        seen = await _until(kid, _is(realtime.STATUS_CHANGED, "lamp-a"))
        assert all(m.get("device_id") != "lamp-b" for m in seen), seen
        done = next(m for m in seen if m["event"] == realtime.COMMAND_COMPLETED)
        assert done["device_id"] == "lamp-a" and done["data"]["source"] == "app"
        assert seen[-1]["data"]["state"]["status"] == "ON"
        assert await kid.nothing_for(0.2)  # trạng thái lamp-b (đọc lại sau lệnh) cũng không lọt

        assert await _until(owner, _is(realtime.STATUS_CHANGED, "lamp-b"))
        await kid.close()
        await owner.close()
        assert ws.mgr.count == 0
    _run(go())


def test_tro_ly_kich_ban_chay_thu_lich_va_scheduler_deu_phat(ws):
    async def go():
        kid = await ws.open_ws("kid1")

        # Trợ lý (nhánh AI — câu phức).
        ws.ai_reply["actions"] = [{"brand": "tuya", "id": "lamp-a", "action": "on", "mode": None}]
        r = await ws.http("owner", "POST", "/api/ai/parse", json={"text": "bật đèn khách và đèn ngủ"})
        assert r.status_code == 200, r.text
        seen = await _until(kid, lambda m: m["event"] == realtime.COMMAND_COMPLETED)
        assert seen[-1]["device_id"] == "lamp-a" and seen[-1]["data"]["source"] == "voice"

        # Kịch bản.
        body = {"name": "Đi ngủ", "actions": [{"device_id": "lamp-a", "action_type": "off"}]}
        sid = (await ws.http("owner", "POST", "/api/scenes", json=body)).json()["data"]["id"]
        assert (await ws.http("owner", "POST", f"/api/scenes/{sid}/run")).json()["status"] == "success"
        seen = await _until(kid, lambda m: m["event"] == realtime.COMMAND_COMPLETED)
        assert seen[-1]["data"]["source"] == "scene" and seen[-1]["data"]["action_label"] == "Tắt"

        sch = ScheduleModel(name="Tối", brand="tuya", device_id="lamp-a", action_type="off",
                            time="22:00", days="", enabled=True)
        ws.db.add(sch)
        ws.db.commit()
        r = await ws.http("owner", "POST", f"/api/schedules/{sch.id}/run")
        assert r.json()["status"] == "success", r.text
        seen = await _until(kid, lambda m: m["event"] == realtime.COMMAND_COMPLETED)
        assert seen[-1]["data"]["source"] == "schedule" and seen[-1]["data"]["action_label"] == "Tắt"

        # Vòng lặp nền của scheduler (không có người bấm).
        await scheduler._fire(ws.db, sch, "on", None, "Lịch “Tối” lúc 22:00", None)
        seen = await _until(kid, lambda m: m["event"] == realtime.COMMAND_COMPLETED)
        assert seen[-1]["data"]["source"] == "schedule" and seen[-1]["data"]["user_name"] is None
        await kid.close()
    _run(go())


def test_lenh_loi_khong_phat_su_kien(ws):
    async def go():
        ws.fail.add("lamp-a")
        kid = await ws.open_ws("kid1")
        r = await ws.http("owner", "GET", "/api/test-control/tuya/lamp-a?action=on")
        assert r.json()["status"] == "error"
        assert await kid.nothing_for(0.3)
        await kid.close()
    _run(go())


def test_doc_trang_thai_tu_may_nay_day_toi_moi_may_cung_tai_khoan(ws):
    async def go():
        phone = await ws.open_ws("kid1")
        tablet = await ws.open_ws("kid1")
        ws.states["lamp-a"] = "ON"  # đổi NGOÀI app (nút vật lý / Smart Life)
        body = (await ws.http("kid1", "GET", "/api/devices/tuya/lamp-a/status?fresh=1")).json()
        assert body["data"]["status"] == "ON" and isinstance(body["read_at_ms"], int)
        for sock in (phone, tablet):
            msg = await sock.receive_json()
            assert msg["event"] == realtime.STATUS_CHANGED
            assert msg["data"]["read_at_ms"] == body["read_at_ms"]
        # Bản cache trả kèm đúng mốc của lần đọc thật, và không phát lại.
        cached = (await ws.http("kid1", "GET", "/api/devices/tuya/lamp-a/status")).json()
        assert cached["cached"] is True and cached["read_at_ms"] == body["read_at_ms"]
        assert await phone.nothing_for(0.2)
        await phone.close()
        await tablet.close()
    _run(go())


def test_watcher_bat_thay_doi_ngoai_app(ws):
    async def go():
        kid = await ws.open_ws("kid1")
        await ws.mgr.watch_once()  # mốc ban đầu
        await _until(kid, _is(realtime.STATUS_CHANGED, "lamp-a"))
        ws.states["lamp-a"] = "ON"  # ai đó bấm công tắc tường
        import app.main as main
        main._status_cache.clear()  # watcher bỏ qua thiết bị vừa đọc < 13s
        await ws.mgr.watch_once()
        seen = await _until(kid, _is(realtime.STATUS_CHANGED, "lamp-a"))
        assert seen[-1]["data"]["state"]["status"] == "ON"
        await kid.close()
    _run(go())


@pytest.mark.parametrize("frame", [
    {"event": "connection.auth", "token": "khong-phai-token"},
    {"event": "connection.auth"},
])
def test_token_sai_hoac_thieu_bi_dong_4401(ws, frame):
    async def go():
        sock = await ws.raw()
        await sock.send_json(frame)
        with pytest.raises(WsClosed) as e:
            await sock.receive_json()
        assert e.value.code == realtime.CLOSE_UNAUTHORIZED
        assert ws.mgr.count == 0 and ws.mgr.legacy_count == 0
    _run(go())


def test_token_qua_header_authorization(ws):
    async def go():
        sock = await ws.raw(headers=[("authorization", f"Bearer {ws.token('kid1')}")])
        assert (await sock.receive_json())["event"] == realtime.READY
        await sock.close()
    _run(go())


def test_tai_khoan_cho_duyet_bi_dong_4403(ws):
    async def go():
        sock = await ws.raw()
        await sock.send_json({"event": realtime.AUTH, "token": ws.token("newbie")})
        with pytest.raises(WsClosed) as e:
            await sock.receive_json()
        assert e.value.code == realtime.CLOSE_FORBIDDEN
    _run(go())


def test_chu_nha_chan_thanh_vien_thi_ket_noi_bi_ngat(ws):
    async def go():
        kid = await ws.open_ws("kid1")
        r = await ws.http("owner", "PATCH", "/api/members/kid1", json={"status": "blocked"})
        assert r.status_code == 200, r.text
        with pytest.raises(WsClosed) as e:
            await kid.receive_json()
        assert e.value.code == realtime.CLOSE_FORBIDDEN
        await kid.close()
        assert ws.mgr.count == 0
    _run(go())


def test_app_cu_khong_token_chi_nhan_echo(ws):
    async def go():
        sock = await ws.raw()
        await sock.send_text("Bạn: bật đèn")
        assert await sock.receive_text() == LEGACY_ECHO
        # Có lệnh thiết bị trong lúc đó: kết nối ẩn danh không bao giờ nhận dữ liệu.
        await ws.http("owner", "GET", "/api/test-control/tuya/lamp-a?action=on")
        assert await sock.nothing_for(0.2)
        await sock.send_text("Bạn: nữa")
        assert await sock.receive_text() == LEGACY_ECHO
        assert ws.mgr.count == 0 and ws.mgr.legacy_count == 1
        await sock.close()
        assert ws.mgr.legacy_count == 0
    _run(go())


def test_ping_pong_va_payload_rac_khong_lam_dong_ket_noi(ws):
    async def go():
        sock = await ws.open_ws("kid1")
        await sock.send_text("{không phải json")
        await sock.send_json(["mảng", "lạ"])
        await sock.send_json({"event": "lạ"})
        await sock.send_json({"event": realtime.PING})
        assert (await sock.receive_json())["event"] == realtime.PONG
        assert ws.mgr.count == 1
        await sock.close()
        assert ws.mgr.count == 0
    _run(go())


def test_qua_nhieu_ket_noi_mot_tai_khoan_bi_tu_choi(ws, monkeypatch):
    monkeypatch.setattr(realtime, "MAX_PER_USER", 2)

    async def go():
        a = await ws.open_ws("kid1")
        b = await ws.open_ws("kid1")
        sock = await ws.raw()
        await sock.send_json({"event": realtime.AUTH, "token": ws.token("kid1")})
        with pytest.raises(WsClosed) as e:
            await sock.receive_json()
        assert e.value.code == realtime.CLOSE_TOO_MANY
        await a.close()
        await b.close()
    _run(go())


def test_db_chua_san_sang_thi_dong_1013(ws, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "db_ready", False)

    async def go():
        sock = await ws.raw()
        with pytest.raises(WsClosed) as e:
            await sock.receive_json()
        assert e.value.code == realtime.CLOSE_UNAVAILABLE
    _run(go())
