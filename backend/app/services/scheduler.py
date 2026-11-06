# backend/app/services/scheduler.py
"""
Bộ máy Hẹn giờ — DÙNG CHUNG cho 2 nơi chạy:
  - vòng lặp trong FastAPI (`scheduler_loop`, lifespan của main.py, role `api`);
  - worker độc lập tại nhà (`backend/worker/`, role `worker`).
Hai nơi chạy CÙNG một thuật toán; chỉ khác session DB và hook sau lệnh.

Thời điểm (giữ nguyên thuật toán cũ):
- Tick mỗi TICK_SECONDS giây, đọc `schedules` (enabled=True).
- Lịch "đến giờ" khi: hôm nay thuộc `days` (rỗng = mỗi ngày) VÀ
  0 <= (now - giờ hẹn hôm nay) < GRACE_SECONDS VÀ chưa kích hoạt hôm nay.
- Lịch KHOẢNG: start và end bắn ĐỘC LẬP; qua đêm (end < start) thì end thuộc
  hôm sau (`_end_days`). One-shot tự tắt sau hành động cuối; lỡ trọn cửa sổ thì
  tự tắt (không bắn nhầm tuần sau).
- Múi giờ cố định Asia/Ho_Chi_Minh.

Chống bắn trùng (MỚI — trước đây đọc rồi gán `last_fired_date` trong Python, hai
tiến trình cùng đọc "chưa bắn" là cùng gửi lệnh):
1. CLAIM nguyên tử: 1 câu UPDATE ... WHERE (compare-and-set) đặt
   `last_fired_date = hôm nay` CHỈ KHI vẫn chưa bắn hôm nay VÀ lịch chưa bị sửa
   (giờ/ngày/thiết bị/hành động khớp lúc đọc). Postgres khóa hàng khi UPDATE —
   transaction thứ hai chờ rồi đánh giá lại WHERE, thấy đã là hôm nay → 0 hàng.
   Cùng transaction: INSERT `schedule_runs` với UNIQUE(schedule_id, part,
   occurrence) — chốt thứ hai. rowcount == 1 và INSERT thành công = được gửi.
2. Đánh dấu TRƯỚC khi gửi (như cũ): lệnh lỗi không tự bắn lặp ở tick sau.
3. Vòng đời `claimed → sending → success|retry|failed`, ghi DB TRƯỚC khi gọi
   connector. Tiến trình chết giữa chừng → hàng kẹt quá LEASE_SECONDS → tiến
   trình còn sống (hoặc chính nó sau restart) phục hồi theo RETRY_POLICIES:
     claimed  = chắc chắn CHƯA gửi → gửi (nếu còn trong cửa sổ).
     sending  = KHÔNG BIẾT đã tới thiết bị chưa → chỉ gửi lại hành động lặp lại
                vô hại; máy cho ăn KHÔNG BAO GIỜ gửi lại.
   Giành lại hàng kẹt cũng là compare-and-set (status + updated_at_ms).

Không dùng advisory lock của Postgres làm cơ chế chính: qua Supabase pooler
(transaction mode) khóa phiên không đáng tin, khóa rò = không ai bắn lịch nào;
và khóa "leader" không bảo vệ được đoạn gửi lệnh nếu leader mất DB mà vẫn có
Internet. Claim theo TỪNG occurrence đúng trên mọi pooler, cả SQLite.
"""
import asyncio
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, TimeoutError as PoolTimeoutError

from app.core.database import AsyncSessionLocal
from app.core.household import scheduler_target_device
from app.models.device import DeviceModel, device_kind
from app.models.schedule import ScheduleModel
from app.models.schedule_run import (
    RUN_ABANDONED, RUN_CLAIMED, RUN_FAILED, RUN_OPEN, RUN_REJECTED, RUN_RETRY, RUN_SENDING,
    RUN_SUCCESS, ScheduleRunModel, SchedulerHeartbeatModel,
)
from . import command_log, realtime
from .connector_manager import device_manager
from .device_actions import normalize_action

logger = logging.getLogger("SmartHome.Scheduler")

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TICK_SECONDS = 30
GRACE_SECONDS = 120

# 1 lần gửi tối đa bao lâu. Tuya cửa = tra loại + stop + 0,4s + lệnh, mỗi call
# timeout 15s. Quá hạn → coi như KHÔNG BIẾT kết quả (thread cũ có thể vẫn gửi).
SEND_TIMEOUT_SECONDS = 60
# Hàng claimed/sending không được cập nhật quá lâu = tiến trình giữ nó đã chết.
# PHẢI > SEND_TIMEOUT_SECONDS, nếu không sẽ giành hàng của tiến trình đang gửi.
LEASE_SECONDS = 90
RETRY_BACKOFF_SECONDS = 30
# Worker coi là còn sống nếu nhịp tim mới hơn ngưỡng này (3 tick).
HEARTBEAT_FRESH_SECONDS = 90
RUN_RETENTION_DAYS = 30
HEARTBEAT_RETENTION_DAYS = 7
HOUSEKEEPING_EVERY_SECONDS = 3600


@dataclass(frozen=True)
class RetryPolicy:
    resend_unknown: bool   # lần gửi trước không xác nhận được → được gửi lại không
    window_seconds: int    # tính từ giờ hẹn; quá cửa sổ thì dừng hẳn
    max_attempts: int


# Theo LOẠI thiết bị (device_kind). Bật/tắt/chế độ lặp lại vô hại. Cửa: mở/đóng/
# dừng lặp lại cũng vô hại, nhưng cửa sổ NGẮN — đóng cửa trễ 10 phút có thể sập
# xuống đúng lúc có người vừa mở ra đi qua. Máy cho ăn: không bao giờ gửi lại sau
# khi đã thử gửi (cho ăn 2 lần tệ hơn lỡ 1 bữa); chỉ phục hồi khi CHẮC CHẮN chưa
# gửi (claimed). Loại chưa rõ: thận trọng như máy cho ăn.
RETRY_POLICIES = {
    "purifier": RetryPolicy(True, 600, 3),
    "switch": RetryPolicy(True, 600, 3),
    "curtain": RetryPolicy(True, 180, 2),
    "feeder": RetryPolicy(False, 600, 1),
    None: RetryPolicy(False, 600, 1),
}


def retry_policy(device) -> RetryPolicy:
    return RETRY_POLICIES.get(device_kind(device), RETRY_POLICIES[None])


async def execute_schedule_action(brand: str, device_id: str, action_type: str,
                                  action_value: Optional[str],
                                  invalidate_cache: Optional[Callable] = None) -> bool:
    """
    Thực thi hành động của 1 lịch qua connector tương ứng.
    Tái dùng đúng primitive hiện có (turn_on/turn_off/set_mode) và invalidate
    cache trạng thái để app đọc được trạng thái mới ngay (giống endpoint control).
    """
    connector = device_manager.get_connector(brand)
    ok = False
    if action_type == "on":
        ok = await connector.turn_on(device_id)
    elif action_type == "off":
        ok = await connector.turn_off(device_id)
    elif action_type == "mode" and hasattr(connector, "set_mode"):
        ok = await connector.set_mode(device_id, action_value or "")
    if invalidate_cache:
        invalidate_cache(brand, device_id)
    return ok


# =========================================================
# Thời điểm (thuật toán gốc, giữ nguyên)
# =========================================================
def _parse_hhmm(time_str) -> Optional[tuple]:
    try:
        hh, mm = map(int, str(time_str).split(":"))
        return hh, mm
    except (ValueError, AttributeError):
        return None


def _delta_seconds(time_str: str, days: str, now: datetime) -> Optional[float]:
    """Giây đã trôi qua kể từ mốc `time_str` hôm nay; None nếu hôm nay không đúng thứ / giờ hỏng."""
    if days:
        dayset = {int(d) for d in days.split(",") if d.strip().isdigit()}
        if dayset and now.weekday() not in dayset:
            return None
    parsed = _parse_hhmm(time_str)
    if parsed is None:
        logger.warning(f"⏰ Giờ hẹn không hợp lệ: {time_str!r}")
        return None
    hh, mm = parsed
    scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return (now - scheduled).total_seconds()


def _is_time_due(time_str: str, days: str, now: datetime) -> bool:
    """Mốc giờ có đang trong cửa sổ kích hoạt [giờ hẹn, +grace) không."""
    delta = _delta_seconds(time_str, days, now)
    return delta is not None and 0 <= delta < GRACE_SECONDS


def _is_time_missed(time_str: str, days: str, now: datetime) -> bool:
    """Hôm nay đúng thứ nhưng cửa sổ kích hoạt đã trôi qua (lỡ hẹn)."""
    delta = _delta_seconds(time_str, days, now)
    return delta is not None and delta >= GRACE_SECONDS


def _end_days(sch) -> str:
    """
    Ngày kích hoạt của HÀNH ĐỘNG KẾT THÚC. Khoảng qua đêm (end < start) thì end
    thuộc NGÀY HÔM SAU -> dịch từng weekday +1 mod 7. days rỗng (mỗi ngày) giữ rỗng.
    """
    start = _parse_hhmm(sch.time)
    end = _parse_hhmm(sch.end_time)
    overnight = start and end and (end[0] * 60 + end[1]) < (start[0] * 60 + start[1])
    if not overnight or not sch.days:
        return sch.days or ""
    return ",".join(str((int(d) + 1) % 7) for d in sch.days.split(",") if d.strip().isdigit())


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _due_at(now: datetime, hhmm: str) -> datetime:
    hh, mm = _parse_hhmm(hhmm)
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


# =========================================================
# Gửi 1 hành động + ghi lịch sử
# =========================================================
async def _fire(db, sch, action_type: str, action_value: Optional[str],
                detail: str, invalidate_cache: Optional[Callable],
                brand: Optional[str] = None) -> tuple:
    """
    Gửi 1 hành động của lịch + ghi lịch sử (nguồn `schedule`, không có người bấm).
    Trả (ok, error). `brand` = hãng lấy từ bảng devices (mặc định sch.brand).
    Quá SEND_TIMEOUT_SECONDS = lỗi (kết quả không biết, không bao giờ báo thành công).
    """
    brand = brand or sch.brand
    ok, error = False, None
    try:
        ok = bool(await asyncio.wait_for(
            execute_schedule_action(brand, sch.device_id, action_type, action_value, invalidate_cache),
            timeout=SEND_TIMEOUT_SECONDS,
        ))
        if not ok:
            logger.warning(f"⏰ Lịch #{sch.id}: thiết bị KHÔNG nhận lệnh ({detail}).")
    except asyncio.TimeoutError:
        error = f"quá {SEND_TIMEOUT_SECONDS}s không phản hồi"
        logger.error(f"⏰ Lịch #{sch.id} quá thời gian gửi lệnh ({detail}).")
    except Exception as e:
        error = str(e)
        logger.error(f"⏰ Lịch #{sch.id} lỗi thực thi ({detail}): {e}")
    try:
        # Bản chụp thuần: record() rollback khi lỗi sẽ expire object ORM, mà
        # notify_command đọc lại thiết bị ngay sau đó.
        device = _plain_device((await db.execute(
            select(DeviceModel).where(DeviceModel.id == sch.device_id)
        )).scalar_one_or_none())
    except Exception as e:  # DB hỏng sau khi đã gửi: vẫn trả kết quả gửi thật
        logger.warning(f"⏰ Không đọc được thiết bị {sch.device_id} để ghi lịch sử: {e}")
        await _safe_rollback(db)
        device = None
    await command_log.record(db, device=device, device_id=sch.device_id, action_type=action_type,
                             action_value=action_value, source="schedule", success=ok,
                             detail=f"{detail}: {error}" if error else detail)
    # Lịch sử trước, /ws sau; lệnh lỗi không phát gì. Không bao giờ ném.
    # Trong worker không có kết nối /ws nào ⇒ no-op (app bắt kịp qua watcher/poll).
    realtime.manager.notify_command(device, action_type=action_type, action_value=action_value,
                                    source="schedule", success=ok)
    return ok, error


def _plain_device(device) -> Optional[SimpleNamespace]:
    """
    Giá trị thuần của 1 hàng thiết bị. Với AsyncSession, `rollback()` LUÔN expire
    mọi object (kể cả expire_on_commit=False) — đọc thuộc tính sau đó là lazy
    load ngoài greenlet → MissingGreenlet. Đủ trường cho device_kind/nhãn/ws.
    """
    if device is None:
        return None
    return SimpleNamespace(id=device.id, name=device.name, brand=device.brand,
                           category=device.category, zone_id=device.zone_id,
                           is_active=device.is_active)


def _plain_run(run: ScheduleRunModel) -> SimpleNamespace:
    """Ảnh chụp 1 hàng schedule_runs (vòng phục hồi đi qua nhiều commit/rollback)."""
    return SimpleNamespace(
        id=run.id, schedule_id=run.schedule_id, part=run.part, occurrence=run.occurrence,
        due_at_ms=run.due_at_ms, label=run.label, device_id=run.device_id, brand=run.brand,
        action_type=run.action_type, action_value=run.action_value, status=run.status,
        attempts=run.attempts, worker_id=run.worker_id, updated_at_ms=run.updated_at_ms,
    )


async def _safe_rollback(db) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


def _is_connection_error(exc: Exception) -> bool:
    """Lỗi mất kết nối DB / hết kết nối trong pool (không phải lỗi dữ liệu của 1 lịch) → bỏ cả tick."""
    if isinstance(exc, (OperationalError, PoolTimeoutError, ConnectionError, OSError)):
        return True
    return isinstance(exc, DBAPIError) and bool(getattr(exc, "connection_invalidated", False))


# =========================================================
# Bộ máy
# =========================================================
@dataclass(frozen=True)
class _Snap:
    """Ảnh chụp 1 lịch lúc đọc — giá trị dùng để quyết định VÀ để compare-and-set."""
    id: int
    name: str
    brand: str
    device_id: str
    action_type: str
    action_value: Optional[str]
    time: str
    days: str
    end_time: Optional[str]
    end_action_type: Optional[str]
    end_action_value: Optional[str]
    one_shot: bool
    last_fired_date: Optional[str]
    last_end_fired_date: Optional[str]

    @classmethod
    def of(cls, s: ScheduleModel) -> "_Snap":
        return cls(s.id, s.name or "", s.brand, s.device_id, s.action_type, s.action_value,
                   s.time, s.days or "", s.end_time, s.end_action_type, s.end_action_value,
                   bool(s.one_shot), s.last_fired_date, s.last_end_fired_date)

    @property
    def label(self) -> str:
        return self.name or f"{self.brand}/{self.device_id}"


def make_worker_id(role: str) -> str:
    """Duy nhất theo TIẾN TRÌNH: restart = id mới (không tự nhận hàng của tiến trình cũ)."""
    name = os.getenv("WORKER_ID", "").strip() or socket.gethostname()
    return f"{role}:{name}#{os.getpid()}-{uuid.uuid4().hex[:4]}"


class ScheduleEngine:
    """
    1 tick = (nhịp tim) → phục hồi hàng kẹt → quét lịch đến hạn → claim → gửi.
    Không giữ trạng thái quan trọng trong RAM: mọi quyết định chống trùng nằm
    trong DB, nên restart / nhiều tiến trình song song đều an toàn.
    """

    def __init__(self, session_factory, *, worker_id: str, role: str,
                 invalidate_cache: Optional[Callable] = None,
                 standby_when_worker_alive: bool = False,
                 use_db_clock: bool = False,
                 info: Optional[str] = None):
        self.session_factory = session_factory
        self.worker_id = worker_id
        self.role = role
        self.invalidate_cache = invalidate_cache
        self.standby_when_worker_alive = standby_when_worker_alive
        # Worker trên Raspberry Pi: Pi không có pin RTC, giờ lúc boot có thể sai
        # tới khi NTP đồng bộ. Lấy giờ của Postgres làm nguồn chuẩn ⇒ không bắn
        # lịch sai giờ; và mọi tiến trình dùng chung MỘT đồng hồ.
        self.use_db_clock = use_db_clock
        self.info = info  # vd "v=abc1234" — hiện ở `python -m worker status`
        self.started_at_ms = command_log.now_ms()
        self._last_housekeeping: Optional[float] = None  # None = dọn ngay tick đầu
        # Độ lệch (ms) giữa đồng hồ của tick (giờ DB) và giờ máy. MỌI mốc thời gian
        # ghi vào schedule_runs / so với lease đều qua `_clock_ms()` — một đồng hồ duy nhất.
        self._offset_ms = 0
        self._standby = False

    # ---------------------------------------------------------- tick
    async def tick(self, now: Optional[datetime] = None) -> dict:
        stats = {"claimed": 0, "sent": 0, "recovered": 0, "disabled": 0, "standby": False}
        async with self.session_factory() as db:
            try:
                now = now or await self._now(db)
                self._offset_ms = _to_ms(now) - command_log.now_ms()
                if self.standby_when_worker_alive and await self._worker_alive(db, now):
                    if not self._standby:
                        logger.info("⏰ Worker tại nhà đang chạy — scheduler này chuyển sang ĐỨNG CHỜ.")
                    self._standby = True
                    stats["standby"] = True
                    await self._heartbeat(db, now, "standby")
                    return stats
                if self._standby:
                    logger.warning("⏰ Không thấy nhịp tim worker — scheduler này TIẾP QUẢN việc bắn lịch.")
                    self._standby = False

                await self._recover(db, now, stats)

                # populate_existing: hàng đã nạp ở bước phục hồi (identity map) phải
                # lấy giá trị DB MỚI — không còn expire-on-commit như Session cũ.
                snaps = [_Snap.of(s) for s in (await db.execute(
                    select(ScheduleModel).where(ScheduleModel.enabled == True)  # noqa: E712
                    .execution_options(populate_existing=True)
                )).scalars().all()]
                await db.commit()  # đóng transaction đọc; mỗi claim là 1 transaction riêng
                for snap in snaps:
                    try:
                        await self._process(db, snap, now, stats)
                    except Exception as e:
                        await _safe_rollback(db)
                        if _is_connection_error(e):
                            raise  # mất DB: dừng cả tick, tick sau thử lại
                        logger.error(f"⏰ Lịch #{snap.id} lỗi xử lý: {e}")

                await self._housekeeping(db, now)
                await self._heartbeat(db, now, "running")
                return stats
            except Exception:
                await _safe_rollback(db)
                raise

    def _clock_ms(self) -> int:
        """Giờ hiện tại theo đồng hồ của tick (giờ DB nếu use_db_clock), tính cả thời gian đã trôi trong tick."""
        return command_log.now_ms() + self._offset_ms

    async def _now(self, db) -> datetime:
        if self.use_db_clock:
            db_now = (await db.execute(text("SELECT clock_timestamp()"))).scalar()
            await db.commit()
            if isinstance(db_now, datetime) and db_now.tzinfo is not None:
                return db_now.astimezone(TZ)
            logger.warning("⏰ Không đọc được giờ DB — dùng giờ máy.")
        return datetime.now(TZ)

    async def _process(self, db, snap: _Snap, now: datetime, stats: dict) -> None:
        today = now.date().isoformat()
        start_due = snap.last_fired_date != today and _is_time_due(snap.time, snap.days, now)
        end_due = bool(
            snap.end_time and snap.last_end_fired_date != today
            and _is_time_due(snap.end_time, _end_days(snap), now)
        )

        # Lịch 1 lần đã LỠ trọn cửa sổ của hành động cuối (máy ngủ/khởi động
        # muộn) -> tự tắt, tránh bắn nhầm vào tuần sau cùng thứ.
        if snap.one_shot and not start_due and not end_due:
            if snap.end_time:
                missed = (snap.last_end_fired_date != today
                          and _is_time_missed(snap.end_time, _end_days(snap), now))
            else:
                missed = (snap.last_fired_date != today
                          and _is_time_missed(snap.time, snap.days, now))
            if missed and await self._disable_missed_one_shot(db, snap, today):
                stats["disabled"] += 1
                logger.warning(f"⏰ Lịch 1 lần #{snap.id} '{snap.label}' đã lỡ giờ — tự tắt.")
            return

        if start_due:
            run_id = await self.claim(db, snap, "start", now)
            if run_id is not None:
                stats["claimed"] += 1
                logger.info(f"⏰ Kích hoạt lịch #{snap.id} '{snap.label}': {snap.action_type} "
                            f"{snap.action_value or ''} lúc {snap.time}")
                if await self._execute(db, run_id, now):
                    stats["sent"] += 1
        if end_due:
            run_id = await self.claim(db, snap, "end", now)
            if run_id is not None:
                stats["claimed"] += 1
                logger.info(f"⏰ Kích hoạt lịch #{snap.id} '{snap.label}' (kết thúc): "
                            f"{snap.end_action_type} {snap.end_action_value or ''} lúc {snap.end_time}")
                if await self._execute(db, run_id, now):
                    stats["sent"] += 1

    # ---------------------------------------------------------- claim
    @staticmethod
    def _unchanged(snap: _Snap):
        """Điều kiện 'lịch chưa bị sửa kể từ lúc đọc' — lệnh cũ không được bắn sau khi sửa."""
        S = ScheduleModel
        return [
            S.id == snap.id,
            S.enabled == True,  # noqa: E712 — render đúng cả SQLite lẫn Postgres
            S.device_id == snap.device_id,
            S.time == snap.time,
            func.coalesce(S.days, "") == snap.days,
            func.coalesce(S.end_time, "") == (snap.end_time or ""),
            func.coalesce(S.one_shot, False) == snap.one_shot,
        ]

    async def claim(self, db, snap: _Snap, part: str, now: datetime) -> Optional[int]:
        """
        Giành quyền bắn 1 occurrence. Trả id hàng schedule_runs, hoặc None nếu
        tiến trình khác đã giành / lịch vừa bị sửa / vừa tắt. Một transaction:
        UPDATE có điều kiện + INSERT nhật ký UNIQUE — một trong hai hụt là rollback.
        """
        S = ScheduleModel
        today = now.date().isoformat()
        if part == "start":
            fired_col, hhmm = S.last_fired_date, snap.time
            action_type, action_value = snap.action_type, snap.action_value
            conds = [S.action_type == snap.action_type,
                     func.coalesce(S.action_value, "") == (snap.action_value or "")]
            final = snap.one_shot and not snap.end_time   # lịch đơn 1 lần: xong hành động duy nhất
        else:
            fired_col, hhmm = S.last_end_fired_date, snap.end_time
            action_type, action_value = snap.end_action_type, snap.end_action_value
            conds = [func.coalesce(S.end_action_type, "") == (snap.end_action_type or ""),
                     func.coalesce(S.end_action_value, "") == (snap.end_action_value or "")]
            final = snap.one_shot                          # hành động CUỐI của lịch khoảng 1 lần

        values = {fired_col.key: today}
        if final:
            values["enabled"] = False
        stmt = (
            update(S)
            .where(*self._unchanged(snap), *conds,
                   or_(fired_col.is_(None), fired_col != today))
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        due = _due_at(now, hhmm)
        now_ms = _to_ms(now)
        try:
            if (await db.execute(stmt)).rowcount != 1:
                await db.rollback()
                logger.info(f"⏰ Lịch #{snap.id} ({part}) đã được tiến trình khác giành hoặc vừa bị sửa — bỏ qua.")
                return None
            run = ScheduleRunModel(
                schedule_id=snap.id, part=part,
                occurrence=f"{today}T{hhmm}", due_at_ms=_to_ms(due), label=snap.label,
                device_id=snap.device_id, brand=snap.brand,
                action_type=action_type, action_value=action_value,
                status=RUN_CLAIMED, attempts=0, worker_id=self.worker_id,
                claimed_at_ms=now_ms, updated_at_ms=now_ms,
            )
            db.add(run)
            await db.commit()
            return run.id
        except IntegrityError:
            await db.rollback()
            logger.info(f"⏰ Lịch #{snap.id} ({part}) occurrence {today}T{hhmm} đã có người chạy — bỏ qua.")
            return None

    async def _disable_missed_one_shot(self, db, snap: _Snap, today: str) -> bool:
        S = ScheduleModel
        fired_col = S.last_end_fired_date if snap.end_time else S.last_fired_date
        stmt = (
            update(S)
            .where(*self._unchanged(snap), or_(fired_col.is_(None), fired_col != today))
            .values(enabled=False)
            .execution_options(synchronize_session=False)
        )
        changed = (await db.execute(stmt)).rowcount == 1
        await db.commit()
        return changed

    # ---------------------------------------------------------- gửi
    async def _execute(self, db, run_id: int, now: datetime) -> bool:
        """
        Gửi lệnh cho 1 hàng `claimed` do CHÍNH tiến trình này giữ.
        Trả True nếu thiết bị nhận lệnh. Lỗi DB trước khi gửi → không gửi, hàng
        vẫn `claimed`, LEASE hết thì được phục hồi.
        """
        R = ScheduleRunModel
        # populate_existing: hàng vừa được giành lại bằng UPDATE Core (_cas_run) —
        # bản trong identity map còn trạng thái CŨ (sending/retry); phải đọc DB.
        run = await db.get(R, run_id, populate_existing=True)
        if run is None or run.status != RUN_CLAIMED or run.worker_id != self.worker_id:
            return False
        detail = self._detail(run)

        # Quyền + chuẩn hóa: thiết bị phải còn trong nhà, hãng lấy từ DB, hành
        # động hợp lệ với LOẠI (cửa không bao giờ nhận on/off).
        device = await scheduler_target_device(db, run.device_id)
        reason = None
        if device is None:
            reason = "thiết bị không còn trong nhà"
        else:
            try:
                action_type, action_value = normalize_action(device, run.action_type, run.action_value)
            except ValueError as e:
                reason = str(e)
        if reason:
            schedule_id, device_id = run.schedule_id, run.device_id
            run_action = (run.action_type, run.action_value)
            await self._finish(db, run_id, RUN_CLAIMED, RUN_REJECTED, now, reason)
            logger.error(f"⏰ Lịch #{schedule_id}: KHÔNG gửi — {reason}.")
            await command_log.record(db, device=device, device_id=device_id,
                                     action_type=run_action[0], action_value=run_action[1],
                                     source="schedule", success=False, detail=f"{detail}: không gửi — {reason}")
            return False
        # Chụp mọi giá trị cần dùng SAU khi gửi: commit làm hết hạn object ORM,
        # đọc lại lúc DB vừa rớt sẽ ném lỗi giữa chừng.
        brand, schedule_id, device_id = device.brand, run.schedule_id, run.device_id
        due_at_ms, attempts_before = run.due_at_ms, run.attempts or 0
        policy = retry_policy(device)
        if brand != run.brand:
            logger.warning(f"⏰ Lịch #{schedule_id}: hãng trong lịch '{run.brand}' khác DB "
                           f"'{brand}' — dùng hãng trong DB.")

        # Ghi `sending` TRƯỚC khi gửi. Ghi không được = không gửi.
        moved = (await db.execute(
            update(R)
            .where(R.id == run_id, R.status == RUN_CLAIMED, R.worker_id == self.worker_id)
            .values(status=RUN_SENDING, attempts=R.attempts + 1, updated_at_ms=self._clock_ms(),
                    brand=brand, action_type=action_type, action_value=action_value)
            .execution_options(synchronize_session=False)
        )).rowcount
        if moved != 1:
            await db.rollback()
            return False
        # Commit = trả kết nối về pool: KHÔNG giữ transaction trong lúc chờ cloud.
        await db.commit()
        attempt = attempts_before + 1
        if attempt > 1:
            detail = f"{detail} (thử lại lần {attempt})"

        target = SimpleNamespace(id=schedule_id, brand=brand, device_id=device_id)
        ok, error = await _fire(db, target, action_type, action_value, detail,
                                self.invalidate_cache, brand=brand)

        if ok:
            status, note = RUN_SUCCESS, None
        else:
            elapsed = (self._clock_ms() - due_at_ms) / 1000
            can_retry = (policy.resend_unknown and attempt < policy.max_attempts
                         and elapsed + RETRY_BACKOFF_SECONDS <= policy.window_seconds)
            status = RUN_RETRY if can_retry else RUN_FAILED
            note = error or "thiết bị không nhận lệnh"
        # Mất DB ở đây: hàng kẹt `sending` → phục hồi coi là KHÔNG BIẾT kết quả.
        await self._finish(db, run_id, RUN_SENDING, status, None, note)
        return ok

    async def _finish(self, db, run_id: int, from_status: str, to_status: str,
                      now: Optional[datetime], detail: Optional[str]) -> bool:
        R = ScheduleRunModel
        try:
            changed = (await db.execute(
                update(R)
                .where(R.id == run_id, R.status == from_status, R.worker_id == self.worker_id)
                .values(status=to_status, detail=(detail or None) and str(detail)[:300],
                        updated_at_ms=_to_ms(now) if now else self._clock_ms())
                .execution_options(synchronize_session=False)
            )).rowcount == 1
            await db.commit()
            return changed
        except Exception as e:
            logger.warning(f"⏰ Không cập nhật được lần chạy #{run_id} → {to_status}: {e}")
            await _safe_rollback(db)
            return False

    @staticmethod
    def _detail(run: ScheduleRunModel) -> str:
        hhmm = run.occurrence.split("T")[-1]
        suffix = " kết thúc" if run.part == "end" else ""
        return f"Lịch “{run.label or run.device_id}”{suffix} lúc {hhmm}"

    # ---------------------------------------------------------- phục hồi
    async def _recover(self, db, now: datetime, stats: dict) -> None:
        """Xử lý hàng kẹt (tiến trình chết) và hàng chờ thử lại."""
        R = ScheduleRunModel
        now_ms = _to_ms(now)
        lease_cut = now_ms - LEASE_SECONDS * 1000
        backoff_cut = now_ms - RETRY_BACKOFF_SECONDS * 1000
        rows = [_plain_run(r) for r in (await db.execute(
            select(R)
            .where(or_(
                (R.status.in_([RUN_CLAIMED, RUN_SENDING])) & (R.updated_at_ms < lease_cut),
                (R.status == RUN_RETRY) & (R.updated_at_ms < backoff_cut),
            ))
            .order_by(R.due_at_ms)
            .limit(50)
            .execution_options(populate_existing=True)
        )).scalars().all()]
        for run in rows:
            try:
                if await self._recover_one(db, run, now):
                    stats["recovered"] += 1
            except Exception as e:
                await _safe_rollback(db)
                if _is_connection_error(e):
                    raise
                logger.error(f"⏰ Phục hồi lần chạy #{run.id} lỗi: {e}")

    async def _recover_one(self, db, run, now: datetime) -> bool:
        """`run` = ảnh chụp (_plain_run), không phải object ORM."""
        run_id, old_status, old_updated = run.id, run.status, run.updated_at_ms
        device = _plain_device(await scheduler_target_device(db, run.device_id))
        policy = retry_policy(device) if device is not None else RETRY_POLICIES[None]
        elapsed = (_to_ms(now) - run.due_at_ms) / 1000
        in_window = elapsed <= policy.window_seconds
        detail = self._detail(run)
        still_wanted = await self._schedule_still_wants(db, run)

        if old_status == RUN_CLAIMED:
            # Chắc chắn CHƯA gửi gì — loại thiết bị nào cũng gửi được.
            go, give_up_status = still_wanted and in_window, RUN_ABANDONED
            give_up_note = ("lịch đã bị sửa/xóa" if not still_wanted
                            else "tiến trình gián đoạn trước khi gửi, đã quá cửa sổ chờ")
        elif old_status == RUN_SENDING:
            # KHÔNG BIẾT đã tới thiết bị chưa.
            go = (still_wanted and in_window and policy.resend_unknown
                  and (run.attempts or 0) < policy.max_attempts)
            give_up_status = RUN_ABANDONED
            give_up_note = ("không xác nhận được kết quả (tiến trình gián đoạn khi đang gửi) — "
                            + ("KHÔNG gửi lại để tránh chạy 2 lần" if not policy.resend_unknown
                               else "đã hết lượt/cửa sổ thử lại"))
        else:  # RUN_RETRY
            go = (still_wanted and in_window and policy.resend_unknown
                  and (run.attempts or 0) < policy.max_attempts)
            give_up_status = RUN_FAILED
            give_up_note = "hết lượt/cửa sổ thử lại" if still_wanted else "lịch đã bị sửa/xóa"

        if not go:
            changed = await self._cas_run(db, run_id, old_status, old_updated,
                                          status=give_up_status, detail=give_up_note)
            if changed:
                logger.warning(f"⏰ Lần chạy #{run_id} (lịch #{run.schedule_id}) dừng: {give_up_note}.")
                if old_status != RUN_RETRY:  # retry đã có dòng lịch sử của lần gửi lỗi
                    await command_log.record(db, device=device, device_id=run.device_id,
                                             action_type=run.action_type, action_value=run.action_value,
                                             source="schedule", success=False,
                                             detail=f"{detail}: {give_up_note}")
            return False

        # Giành lại hàng (compare-and-set) rồi gửi như một claim mới của mình.
        if not await self._cas_run(db, run_id, old_status, old_updated, status=RUN_CLAIMED,
                                   worker_id=self.worker_id):
            return False
        logger.warning(f"⏰ Phục hồi lần chạy #{run_id} (lịch #{run.schedule_id}, trạng thái cũ "
                       f"{old_status}, đã thử {run.attempts or 0} lần).")
        await self._execute(db, run_id, now)
        return True

    async def _cas_run(self, db, run_id: int, old_status: str, old_updated: int, **values) -> bool:
        R = ScheduleRunModel
        if "detail" in values and values["detail"]:
            values["detail"] = str(values["detail"])[:300]
        values["updated_at_ms"] = self._clock_ms()
        changed = (await db.execute(
            update(R)
            .where(R.id == run_id, R.status == old_status, R.updated_at_ms == old_updated)
            .values(**values)
            .execution_options(synchronize_session=False)
        )).rowcount == 1
        await db.commit()
        return changed

    @staticmethod
    async def _schedule_still_wants(db, run) -> bool:
        """
        Lịch còn tồn tại, cùng thiết bị + giờ + hành động, và chưa bị tắt tay
        (one-shot tự tắt lúc claim nên không xét enabled). Sửa/xóa lịch sau khi
        claim = không gửi lại lệnh cũ.
        """
        sch = await db.get(ScheduleModel, run.schedule_id, populate_existing=True)
        if sch is None or sch.device_id != run.device_id:
            return False
        if not sch.enabled and not sch.one_shot:
            return False
        hhmm = run.occurrence.split("T")[-1]
        if run.part == "start":
            want_time, want = sch.time, (sch.action_type, sch.action_value)
        else:
            want_time, want = sch.end_time, (sch.end_action_type, sch.end_action_value)
        return want_time == hhmm and _action_key(*want) == _action_key(run.action_type, run.action_value)

    # ---------------------------------------------------------- nhịp tim
    async def _heartbeat(self, db, now: datetime, state: str, detail: Optional[str] = None) -> None:
        H = SchedulerHeartbeatModel
        hb = await db.get(H, self.worker_id, populate_existing=True)
        if hb is None:
            hb = H(worker_id=self.worker_id, role=self.role, host=socket.gethostname(),
                   pid=os.getpid(), started_at_ms=self.started_at_ms)
            db.add(hb)
        hb.state = state
        hb.last_seen_ms = _to_ms(now)
        detail = detail or self.info
        hb.detail = (detail or None) and str(detail)[:300]
        await db.commit()

    async def mark_stopped(self) -> None:
        """Gọi lúc tắt sạch: Render (auto) tiếp quản ngay, không chờ nhịp tim hết hạn."""
        async with self.session_factory() as db:
            try:
                await self._heartbeat(db, datetime.fromtimestamp(self._clock_ms() / 1000, TZ), "stopped")
            except Exception as e:
                logger.warning(f"⏰ Không ghi được trạng thái dừng: {e}")
                await _safe_rollback(db)

    async def _worker_alive(self, db, now: datetime) -> bool:
        H = SchedulerHeartbeatModel
        cut = _to_ms(now) - HEARTBEAT_FRESH_SECONDS * 1000
        last = (await db.execute(
            select(func.max(H.last_seen_ms))
            .where(H.role == "worker", H.state == "running", H.last_seen_ms >= cut)
        )).scalar()
        return last is not None

    async def _housekeeping(self, db, now: datetime) -> None:
        if (self._last_housekeeping is not None
                and time.monotonic() - self._last_housekeeping < HOUSEKEEPING_EVERY_SECONDS):
            return
        self._last_housekeeping = time.monotonic()
        R, H = ScheduleRunModel, SchedulerHeartbeatModel
        now_ms = _to_ms(now)
        try:
            n_runs = (await db.execute(
                delete(R)
                .where(R.updated_at_ms < now_ms - RUN_RETENTION_DAYS * 86_400_000,
                       R.status.notin_(RUN_OPEN))
                .execution_options(synchronize_session=False)
            )).rowcount
            n_hb = (await db.execute(
                delete(H)
                .where(H.last_seen_ms < now_ms - HEARTBEAT_RETENTION_DAYS * 86_400_000)
                .execution_options(synchronize_session=False)
            )).rowcount
            await db.commit()
            if n_runs or n_hb:
                logger.info(f"⏰ Dọn {n_runs} lần chạy cũ, {n_hb} nhịp tim cũ.")
        except Exception as e:
            logger.warning(f"⏰ Dọn dẹp nhật ký lịch lỗi: {e}")
            await _safe_rollback(db)


def _action_key(action_type, action_value) -> tuple:
    """Dạng so sánh của 1 hành động. `_execute` lưu bản ĐÃ chuẩn hóa vào hàng
    (on/off bỏ value, mode viết thường) — lịch gốc phải so theo cùng dạng."""
    if action_type in ("on", "off"):
        return (action_type, None)
    return (action_type, str(action_value or "").lower())


# =========================================================
# Vòng lặp
# =========================================================
async def run_forever(engine: ScheduleEngine, stop: Optional[asyncio.Event] = None,
                      tick_seconds: int = TICK_SECONDS) -> None:
    """
    Tick đều đặn tới khi `stop` được bật. Lỗi (mất mạng/DB) không dừng vòng lặp:
    tick sau thử lại — pool_pre_ping tự nối lại. Log lỗi lần đầu + mỗi ~10 phút
    (không xả stack trace mỗi 30s), và log khi khôi phục.
    Tick đang chạy không bị cắt ngang khi dừng (đang gửi lệnh cửa dở dang là tệ nhất).
    """
    stop = stop or asyncio.Event()
    failures = 0
    while not stop.is_set():
        started = time.monotonic()
        try:
            await engine.tick()
            if failures:
                logger.warning(f"⏰ Scheduler KHÔI PHỤC sau {failures} tick lỗi liên tiếp.")
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            failures += 1
            if failures == 1 or failures % 20 == 0:
                logger.error(f"⏰ Scheduler tick lỗi ({failures} lần liên tiếp): {e}")
        wait = max(1.0, tick_seconds - (time.monotonic() - started))
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass


def scheduler_mode() -> str:
    """
    SCHEDULER_ENABLED cho vòng lặp TRONG FastAPI (Render):
      không đặt / 1  → "on":   chạy như trước (giờ đã có claim nguyên tử);
      0              → "off":  không chạy — worker tại nhà lo hết;
      auto           → "auto": đứng chờ khi worker còn nhịp tim, tự tiếp quản khi
                               worker im lặng > HEARTBEAT_FRESH_SECONDS.
    Giá trị lạ → "on" (an toàn: chạy song song không bắn trùng nhờ claim).
    """
    raw = os.getenv("SCHEDULER_ENABLED", "").strip().lower()
    if raw in ("", "1", "true", "on", "yes"):
        return "on"
    if raw in ("0", "false", "off", "no"):
        return "off"
    if raw == "auto":
        return "auto"
    logger.error(f"⏰ SCHEDULER_ENABLED={raw!r} không hợp lệ (0|1|auto) — coi là 1.")
    return "on"


async def scheduler_loop(invalidate_cache: Optional[Callable] = None, mode: str = "on",
                         session_factory=None):
    """Vòng lặp nền trong FastAPI (role `api`). Dừng bằng cancel task như trước."""
    engine = ScheduleEngine(
        session_factory or AsyncSessionLocal, worker_id=make_worker_id("api"), role="api",
        invalidate_cache=invalidate_cache, standby_when_worker_alive=(mode == "auto"),
    )
    logger.info(f"⏰ Scheduler Hẹn giờ bắt đầu chạy (tick {TICK_SECONDS}s, grace {GRACE_SECONDS}s, "
                f"chế độ {mode}, id {engine.worker_id})...")
    try:
        await run_forever(engine)
    except asyncio.CancelledError:
        logger.info("⏰ Scheduler nhận lệnh dừng.")
        # Task đã bị hủy: ghi "stopped" trong task con được che chắn để lần
        # await này không bị chính lệnh hủy cắt ngang.
        try:
            await asyncio.shield(engine.mark_stopped())
        except BaseException:
            pass
        raise
