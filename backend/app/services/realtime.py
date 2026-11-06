# backend/app/services/realtime.py
"""
Kênh thời gian thực `/ws`: đẩy trạng thái thiết bị tới app.

Ba phần:
  1. `ConnectionManager` — giữ kết nối ĐÃ XÁC THỰC (nhiều máy / 1 tài khoản),
     mỗi kết nối gửi có khóa + timeout riêng ⇒ 1 kết nối treo/lỗi bị gỡ mà
     không làm chậm hay hỏng các kết nối khác. Heartbeat: server ping mỗi
     PING_INTERVAL, kết nối im lặng quá DEAD_AFTER bị coi là chết.
  2. Phát sự kiện:
       - `notify_state()` — gọi sau MỖI lần đọc trạng thái THẬT (không phải
         cache). Chỉ phát khi trạng thái ĐỔI so với lần phát trước; lần đọc cũ
         về muộn (read_at nhỏ hơn) bị bỏ. Chuyển qua/lại `offline` phát thêm
         `device.offline` / `device.online`.
       - `notify_command()` — gọi SAU khi connector trả kết quả và đã ghi lịch
         sử. Lệnh lỗi KHÔNG phát gì (không bao giờ báo thành công giả). Lệnh
         thành công phát `device.command_completed` rồi hẹn đọc lại vài nhịp để
         phát trạng thái mới (cloud cần vài giây để phản ánh lệnh).
  3. Watcher — khi có ≥1 kết nối, đọc định kỳ (WATCH_INTERVAL) các thiết bị cần
     theo dõi để bắt thay đổi NGOÀI hệ thống (app Smart Life/VeSync, nút vật
     lý): các hãng không đẩy sự kiện về backend này. Một watcher cho cả nhà
     thay cho mỗi điện thoại tự poll 6s. Không ai kết nối ⇒ không đọc gì.

Module này KHÔNG đụng DB hay luật quyền: main.py cắm vào qua `configure()`.
Quyền ai nhận sự kiện nào do `core/household.realtime_audience` quyết định,
đánh giá lại MỖI lần phát ⇒ đổi khu / chặn có hiệu lực ngay sự kiện kế tiếp.

Payload thống nhất (server → app):
    {"event": "...", "device_id": "<id>|null", "timestamp": <ms phát>, "data": {...}}
"""
import asyncio
import itertools
import json
import logging
import time
from typing import Awaitable, Callable, Optional

from .command_log import action_label, member_name

logger = logging.getLogger("SmartHome.Realtime")

# ----------------------------------------------------------------- hằng số
PING_INTERVAL = 25.0       # < idle timeout của proxy Render; app trả pong
DEAD_AFTER = 75.0          # 3 nhịp ping không thấy gì từ app ⇒ kết nối chết
SEND_TIMEOUT = 5.0         # 1 socket treo không được giữ chân vòng phát
REVALIDATE_EVERY = 120.0   # kiểm lại trạng thái thành viên (chặn/xóa) định kỳ
WATCH_INTERVAL = 15.0      # watcher đọc thiết bị cần theo dõi (app cũ poll 6s)
FOLLOWUP_DELAYS = (1.5, 5.0)
DOOR_SETTLE_DELAY = 32.0   # > _DOOR_TRAVEL_SECONDS (30s) của Tuya: opening → open
MAX_PER_USER = 10          # chặn 1 tài khoản mở vô hạn kết nối
MAX_LEGACY = 20            # kết nối kiểu cũ (echo, KHÔNG có dữ liệu thiết bị)

# Mã đóng kết nối (4xxx = ứng dụng tự định nghĩa).
CLOSE_UNAUTHORIZED = 4401  # token sai/hết hạn
CLOSE_FORBIDDEN = 4403     # chờ duyệt / bị chặn / không còn trong nhà
CLOSE_TOO_MANY = 4429
CLOSE_UNAVAILABLE = 1013   # DB chưa sẵn sàng — thử lại sau

# Sự kiện
STATUS_CHANGED = "device.status_changed"
COMMAND_COMPLETED = "device.command_completed"
DEVICE_OFFLINE = "device.offline"
DEVICE_ONLINE = "device.online"
PING = "connection.ping"
PONG = "connection.pong"
READY = "connection.ready"
AUTH = "connection.auth"   # app → server, frame đầu tiên

# Loại thiết bị watcher theo dõi. Máy cho ăn KHÔNG (khớp app: tiết kiệm quota
# Tuya; trạng thái của nó chỉ đổi khi cho ăn — đã có đọc lại sau lệnh).
WATCHED_KINDS = ("purifier", "curtain", "switch")

# (device_id, user_ids) -> (được nhận, phải ngắt). device_id None = chỉ kiểm thành viên.
AudienceFn = Callable[[Optional[str], set], Awaitable[tuple]]
# (device_id, brand, name, max_age) -> đọc thật nếu cache cũ hơn max_age, rồi notify_state.
RefreshFn = Callable[[str, str, Optional[str], float], Awaitable[None]]
# () -> [(device_id, brand, name)] cần watcher theo dõi.
TargetsFn = Callable[[], Awaitable[list]]


def now_ms() -> int:
    return int(time.time() * 1000)


def make_event(event: str, device_id: Optional[str] = None, data: Optional[dict] = None) -> dict:
    return {"event": event, "device_id": device_id, "timestamp": now_ms(), "data": data or {}}


def _state_key(state: dict) -> str:
    """Dạng so sánh của trạng thái (bỏ device_id — không phải trạng thái)."""
    return json.dumps({k: v for k, v in state.items() if k != "device_id"},
                      sort_keys=True, default=str)


def _is_offline(state: dict) -> bool:
    return str(state.get("status", "")).lower() == "offline"


_conn_ids = itertools.count(1)


class Connection:
    """1 socket đã xác thực. Mọi lần gửi đi qua khóa riêng + timeout."""

    def __init__(self, ws, user_id: str):
        self.id = next(_conn_ids)
        self.ws = ws
        self.user_id = user_id
        self.last_seen = time.monotonic()
        self.closed = False
        self._lock = asyncio.Lock()

    def touch(self) -> None:
        self.last_seen = time.monotonic()

    async def send(self, payload: dict) -> bool:
        if self.closed:
            return False
        try:
            text = json.dumps(payload, ensure_ascii=False, default=str)
            async with self._lock:
                await asyncio.wait_for(self.ws.send_text(text), SEND_TIMEOUT)
            return True
        except Exception as e:
            logger.info(f"WS #{self.id} gửi lỗi ({type(e).__name__}) — sẽ gỡ kết nối.")
            return False

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await asyncio.wait_for(self.ws.close(code=code, reason=reason), SEND_TIMEOUT)
        except Exception:
            pass  # socket đã chết: không còn gì để đóng


class ConnectionManager:
    def __init__(self):
        self._conns: dict[int, Connection] = {}
        self.legacy_count = 0
        self._audience: Optional[AudienceFn] = None
        self._refresh: Optional[RefreshFn] = None
        self._targets: Optional[TargetsFn] = None
        # device_id -> {"key", "at" (read_at_ms), "offline"}: lần phát gần nhất
        self._last_state: dict[str, dict] = {}
        self._followups: dict[str, asyncio.Task] = {}
        self._bg: set[asyncio.Task] = set()
        self._loops: list[asyncio.Task] = []
        self._last_revalidate = time.monotonic()

    # ------------------------------------------------------------ cấu hình
    def configure(self, *, audience: AudienceFn, refresh: RefreshFn, targets: TargetsFn) -> None:
        self._audience, self._refresh, self._targets = audience, refresh, targets

    def start(self) -> None:
        """Chạy heartbeat + watcher (gọi trong lifespan)."""
        if self._loops:
            return
        self._loops = [asyncio.create_task(self._heartbeat_loop()),
                       asyncio.create_task(self._watch_loop())]

    async def stop(self) -> None:
        tasks = self._loops + list(self._followups.values()) + list(self._bg)
        self._loops = []
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for c in list(self._conns.values()):
            await c.close(1001, "server shutdown")
        self._conns.clear()

    # ------------------------------------------------------------ kết nối
    @property
    def count(self) -> int:
        return len(self._conns)

    def user_count(self, user_id: str) -> int:
        return sum(1 for c in self._conns.values() if c.user_id == user_id)

    def add(self, conn: Connection) -> None:
        self._conns[conn.id] = conn
        logger.info(f"WS #{conn.id} vào ({conn.user_id}); đang mở {self.count} kết nối.")

    def remove(self, conn: Connection) -> None:
        if self._conns.pop(conn.id, None) is not None:
            logger.info(f"WS #{conn.id} ra; còn {self.count} kết nối.")

    async def _drop(self, conn: Connection, code: int, reason: str) -> None:
        self.remove(conn)
        await conn.close(code, reason)

    # ------------------------------------------------------------ phát
    def _spawn(self, coro) -> None:
        """Chạy nền (không bắt lệnh điều khiển phải chờ việc phát). Lỗi chỉ log."""
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:  # không có event loop (gọi từ ngữ cảnh đồng bộ lạ)
            coro.close()
            return
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        task.add_done_callback(_log_task_error)

    async def broadcast_device(self, device_id: str, payloads: list[dict]) -> int:
        """
        Gửi `payloads` tới mọi kết nối được phép thấy `device_id`. Trả số
        kết nối nhận được. Không xác định được quyền ⇒ KHÔNG gửi (fail closed).
        """
        conns = [c for c in self._conns.values() if not c.closed]
        if not conns or self._audience is None:
            return 0
        try:
            allowed, revoked = await self._audience(device_id, {c.user_id for c in conns})
        except Exception as e:
            logger.warning(f"WS: không xác định được người nhận {device_id} — bỏ phát: {e}")
            return 0
        for c in conns:
            if c.user_id in revoked:
                await self._drop(c, CLOSE_FORBIDDEN, "member not active")
        targets = [c for c in conns if c.user_id in allowed and c.user_id not in revoked]
        delivered = 0
        for payload in payloads:
            batch = [c for c in targets if not c.closed]
            results = await asyncio.gather(*(c.send(payload) for c in batch))
            for c, ok in zip(batch, results):
                if ok:
                    delivered += 1
                else:
                    await self._drop(c, 1011, "send failed")
        return delivered

    def notify_state(self, device_id: str, brand: str, state, read_at_ms: int) -> None:
        """
        Gọi sau MỖI lần đọc trạng thái thật. So sánh ĐỒNG BỘ (thứ tự xác định),
        việc gửi chạy nền. Không đổi / lần đọc cũ về muộn ⇒ không phát gì.
        Không bao giờ ném: phát lỗi không được làm hỏng lần đọc.
        """
        try:
            self._notify_state(device_id, brand, state, read_at_ms)
        except Exception as e:
            logger.warning(f"WS notify_state {device_id} lỗi: {e}")

    def _notify_state(self, device_id: str, brand: str, state, read_at_ms: int) -> None:
        if not isinstance(state, dict) or not device_id:
            return
        key = _state_key(state)
        offline = _is_offline(state)
        prev = self._last_state.get(device_id)
        if prev is not None and (prev["at"] > read_at_ms or prev["key"] == key):
            return
        self._last_state[device_id] = {"key": key, "at": read_at_ms, "offline": offline}

        payloads = [make_event(STATUS_CHANGED, device_id,
                               {"brand": brand, "state": state, "read_at_ms": read_at_ms})]
        if offline and (prev is None or not prev["offline"]):
            payloads.append(make_event(DEVICE_OFFLINE, device_id, {"brand": brand, "read_at_ms": read_at_ms}))
        elif not offline and prev is not None and prev["offline"]:
            payloads.append(make_event(DEVICE_ONLINE, device_id, {"brand": brand, "read_at_ms": read_at_ms}))
        if self._conns:
            self._spawn(self.broadcast_device(device_id, payloads))

    def notify_command(self, device, *, action_type: Optional[str], action_value: Optional[str],
                       source: str, success: Optional[bool], member=None) -> None:
        """
        Gọi SAU khi connector trả kết quả + đã ghi lịch sử. Chỉ lệnh THÀNH CÔNG
        mới phát. Không ai kết nối ⇒ không làm gì (kể cả không đọc lại — không
        đốt quota Tuya khi không ai xem). Không bao giờ ném.
        """
        try:
            self._notify_command(device, action_type=action_type, action_value=action_value,
                                 source=source, success=success, member=member)
        except Exception as e:
            logger.warning(f"WS notify_command lỗi: {e}")

    def _notify_command(self, device, *, action_type, action_value, source, success, member) -> None:
        if success is not True or device is None or not self._conns:
            return
        device_id = getattr(device, "id", None)
        brand = getattr(device, "brand", None)
        if not device_id or not brand:
            return
        payload = make_event(COMMAND_COMPLETED, device_id, {
            "brand": brand,
            "action_type": action_type,
            "action_value": action_value,
            "action_label": action_label(device, action_type, action_value),
            "source": source,
            "user_name": member_name(member),
            "success": True,
        })
        self._spawn(self.broadcast_device(device_id, [payload]))
        from app.models.device import device_kind  # tránh vòng import lúc nạp module
        is_door = device_kind(device) == "curtain"
        self._schedule_followup(device_id, brand, getattr(device, "name", None), is_door)

    def _schedule_followup(self, device_id: str, brand: str, name: Optional[str], is_door: bool) -> None:
        """Đọc lại sau lệnh. Lệnh mới thay lịch đọc của lệnh cũ (không chồng chất)."""
        old = self._followups.pop(device_id, None)
        if old is not None:
            old.cancel()
        delays = FOLLOWUP_DELAYS + ((DOOR_SETTLE_DELAY,) if is_door else ())
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._followup(device_id, brand, name, delays))
        self._followups[device_id] = task
        task.add_done_callback(_log_task_error)

    async def _followup(self, device_id: str, brand: str, name: Optional[str], delays) -> None:
        elapsed = 0.0
        try:
            for d in delays:
                await asyncio.sleep(d - elapsed)
                elapsed = d
                if not self._conns or self._refresh is None:
                    return
                # max_age 1.2s: app vừa đọc fresh (vòng xác nhận sau lệnh) thì
                # dùng luôn kết quả đó, không gọi cloud lần nữa.
                try:
                    await self._refresh(device_id, brand, name, 1.2)
                except Exception as e:
                    logger.info(f"WS: đọc lại {device_id} sau lệnh lỗi: {e}")
        finally:
            if self._followups.get(device_id) is asyncio.current_task():
                self._followups.pop(device_id, None)

    # ------------------------------------------------------------ heartbeat
    async def heartbeat_once(self) -> None:
        now = time.monotonic()
        for c in list(self._conns.values()):
            if now - c.last_seen > DEAD_AFTER:
                logger.info(f"WS #{c.id} im lặng {now - c.last_seen:.0f}s — coi là chết.")
                await self._drop(c, 1001, "heartbeat timeout")
        conns = list(self._conns.values())
        results = await asyncio.gather(*(c.send(make_event(PING)) for c in conns))
        for c, ok in zip(conns, results):
            if not ok:
                await self._drop(c, 1011, "send failed")
        if now - self._last_revalidate >= REVALIDATE_EVERY:
            self._last_revalidate = now
            await self.revalidate_users()

    async def revalidate_users(self, user_ids: Optional[set] = None) -> None:
        """Ngắt kết nối của thành viên không còn active (bị chặn / chờ duyệt / bị xóa)."""
        conns = [c for c in self._conns.values() if user_ids is None or c.user_id in user_ids]
        if not conns or self._audience is None:
            return
        try:
            _, revoked = await self._audience(None, {c.user_id for c in conns})
        except Exception as e:
            logger.warning(f"WS: kiểm lại thành viên lỗi: {e}")
            return
        for c in conns:
            if c.user_id in revoked:
                await self._drop(c, CLOSE_FORBIDDEN, "member not active")

    def revalidate_soon(self, user_id: str) -> None:
        """Chủ nhà vừa đổi vai/trạng thái của `user_id` — kiểm lại ngay, không đợi 2 phút."""
        if any(c.user_id == user_id for c in self._conns.values()):
            self._spawn(self.revalidate_users({user_id}))

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await self.heartbeat_once()
            except Exception as e:
                logger.warning(f"WS heartbeat lỗi: {e}")

    # ------------------------------------------------------------ watcher
    async def watch_once(self) -> int:
        """1 vòng đọc các thiết bị cần theo dõi. Trả số thiết bị đã đưa vào đọc."""
        if not self._conns or self._targets is None or self._refresh is None:
            return 0
        targets = await self._targets()
        # Đọc trong 13s gần đây (app đang poll dự phòng, đọc sau lệnh...) thì bỏ.
        max_age = WATCH_INTERVAL - 2
        results = await asyncio.gather(
            *(self._refresh(dev_id, brand, name, max_age) for dev_id, brand, name in targets),
            return_exceptions=True,
        )
        for (dev_id, _, _), r in zip(targets, results):
            if isinstance(r, Exception):
                logger.info(f"WS watcher: đọc {dev_id} lỗi: {r}")
        return len(targets)

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(WATCH_INTERVAL)
            try:
                await self.watch_once()
            except Exception as e:
                logger.warning(f"WS watcher lỗi: {e}")


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning(f"WS tác vụ nền lỗi: {task.exception()!r}")


manager = ConnectionManager()
