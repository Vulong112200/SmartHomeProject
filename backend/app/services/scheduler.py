# backend/app/services/scheduler.py
"""
Vòng lặp Hẹn giờ chạy nền (asyncio task, khởi động trong lifespan của main.py).

Cách hoạt động:
- Tick mỗi TICK_SECONDS giây, đọc bảng `schedules` (enabled=True) từ SQLite.
- Lịch "đến giờ" khi: hôm nay thuộc `days` (hoặc days rỗng = mỗi ngày) VÀ
  0 <= (now - giờ hẹn hôm nay) < GRACE_SECONDS VÀ chưa kích hoạt hôm nay
  (last_fired_date != hôm nay).
- Grace 120s + tick 30s + server luôn thức (UptimeRobot ping /health) đảm bảo
  không trượt phút hẹn; last_fired_date chặn kích hoạt lặp trong cùng ngày.
- Múi giờ cố định Asia/Ho_Chi_Minh (server Render chạy UTC).
"""
import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from app.core.database import SessionLocal
from app.models.schedule import ScheduleModel
from .connector_manager import device_manager

logger = logging.getLogger("SmartHome.Scheduler")

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TICK_SECONDS = 30
GRACE_SECONDS = 120


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


def _end_days(sch: ScheduleModel) -> str:
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


async def scheduler_loop(invalidate_cache: Optional[Callable] = None):
    """Vòng lặp nền: quét & kích hoạt các lịch đến giờ. Lỗi 1 lịch không dừng vòng lặp."""
    logger.info(f"⏰ Scheduler Hẹn giờ bắt đầu chạy (tick {TICK_SECONDS}s, grace {GRACE_SECONDS}s)...")
    while True:
        try:
            now = datetime.now(TZ)
            today = now.date().isoformat()
            db = SessionLocal()
            try:
                for sch in db.query(ScheduleModel).filter(ScheduleModel.enabled == True).all():
                    label = sch.name or f"{sch.brand}/{sch.device_id}"
                    start_due = sch.last_fired_date != today and _is_time_due(sch.time, sch.days or "", now)
                    end_due = bool(
                        sch.end_time and sch.last_end_fired_date != today
                        and _is_time_due(sch.end_time, _end_days(sch), now)
                    )

                    # Lịch 1 lần đã LỠ trọn cửa sổ của hành động cuối (server ngủ/khởi động
                    # muộn) -> tự tắt, tránh bắn nhầm vào tuần sau cùng thứ.
                    if sch.one_shot and not start_due and not end_due:
                        if sch.end_time:
                            missed = (sch.last_end_fired_date != today
                                      and _is_time_missed(sch.end_time, _end_days(sch), now))
                        else:
                            missed = (sch.last_fired_date != today
                                      and _is_time_missed(sch.time, sch.days or "", now))
                        if missed:
                            sch.enabled = False
                            db.commit()
                            logger.warning(f"⏰ Lịch 1 lần #{sch.id} '{label}' đã lỡ giờ — tự tắt.")
                        continue

                    # Đánh dấu ĐÃ kích hoạt TRƯỚC khi gửi lệnh — nếu lệnh chậm/lỗi
                    # cũng không bắn lặp lại ở tick sau (an toàn hơn với thiết bị motor).
                    if start_due:
                        sch.last_fired_date = today
                        if sch.one_shot and not sch.end_time:
                            sch.enabled = False  # lịch đơn 1 lần: xong hành động duy nhất
                        db.commit()
                        logger.info(f"⏰ Kích hoạt lịch #{sch.id} '{label}': {sch.action_type} {sch.action_value or ''} lúc {sch.time}")
                        try:
                            ok = await execute_schedule_action(
                                sch.brand, sch.device_id, sch.action_type, sch.action_value,
                                invalidate_cache,
                            )
                            if not ok:
                                logger.warning(f"⏰ Lịch #{sch.id}: thiết bị KHÔNG nhận lệnh.")
                        except Exception as e:
                            logger.error(f"⏰ Lịch #{sch.id} lỗi thực thi: {e}")

                    if end_due:
                        sch.last_end_fired_date = today
                        if sch.one_shot:
                            sch.enabled = False  # hành động CUỐI của lịch khoảng 1 lần
                        db.commit()
                        logger.info(f"⏰ Kích hoạt lịch #{sch.id} '{label}' (kết thúc): {sch.end_action_type} {sch.end_action_value or ''} lúc {sch.end_time}")
                        try:
                            ok = await execute_schedule_action(
                                sch.brand, sch.device_id, sch.end_action_type, sch.end_action_value,
                                invalidate_cache,
                            )
                            if not ok:
                                logger.warning(f"⏰ Lịch #{sch.id} (kết thúc): thiết bị KHÔNG nhận lệnh.")
                        except Exception as e:
                            logger.error(f"⏰ Lịch #{sch.id} (kết thúc) lỗi thực thi: {e}")
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("⏰ Scheduler nhận lệnh dừng.")
            raise
        except Exception as e:
            logger.error(f"⏰ Scheduler tick lỗi: {e}")
        await asyncio.sleep(TICK_SECONDS)
