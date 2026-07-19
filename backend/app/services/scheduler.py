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


def _is_due(schedule: ScheduleModel, now: datetime) -> bool:
    """Kiểm tra lịch có đến giờ kích hoạt tại thời điểm `now` không."""
    if schedule.days:
        days = {int(d) for d in schedule.days.split(",") if d.strip().isdigit()}
        if days and now.weekday() not in days:
            return False
    try:
        hh, mm = map(int, str(schedule.time).split(":"))
    except (ValueError, AttributeError):
        logger.warning(f"Lịch #{schedule.id} có giờ không hợp lệ: {schedule.time!r}")
        return False
    scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    delta = (now - scheduled).total_seconds()
    return 0 <= delta < GRACE_SECONDS


async def scheduler_loop(invalidate_cache: Optional[Callable] = None):
    """Vòng lặp nền: quét & kích hoạt các lịch đến giờ. Lỗi 1 lịch không dừng vòng lặp."""
    logger.info(f"⏰ Scheduler Hẹn giờ bắt đầu chạy (tick {TICK_SECONDS}s, grace {GRACE_SECONDS}s)...")
    while True:
        try:
            now = datetime.now(TZ)
            today = now.date().isoformat()
            db = SessionLocal()
            try:
                due = [
                    s for s in db.query(ScheduleModel).filter(ScheduleModel.enabled == True).all()
                    if s.last_fired_date != today and _is_due(s, now)
                ]
                for sch in due:
                    # Đánh dấu ĐÃ kích hoạt TRƯỚC khi gửi lệnh — nếu lệnh chậm/lỗi
                    # cũng không bắn lặp lại ở tick sau (an toàn hơn với thiết bị motor).
                    sch.last_fired_date = today
                    db.commit()
                    label = sch.name or f"{sch.brand}/{sch.device_id}"
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
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("⏰ Scheduler nhận lệnh dừng.")
            raise
        except Exception as e:
            logger.error(f"⏰ Scheduler tick lỗi: {e}")
        await asyncio.sleep(TICK_SECONDS)
