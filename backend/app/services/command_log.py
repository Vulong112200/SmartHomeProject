"""
Ghi lịch sử lệnh điều khiển (bảng `command_logs`).

Mọi đường gửi lệnh của hệ thống gọi `record()` SAU khi connector trả kết quả:
endpoint control (app/widget/shortcut), trợ lý giọng nói, kịch bản, lịch hẹn
(cả vòng lặp nền lẫn "chạy thử"). Sự kiện từ bên ngoài (nút vật lý...) do
`services/device_history.py` ghi.

Ghi lịch sử KHÔNG BAO GIỜ được làm hỏng lệnh: lỗi DB ở đây chỉ log cảnh báo.
"""
import logging
import time
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.command_log import CommandLogModel
from app.models.device import device_kind

logger = logging.getLogger(__name__)

# Nguồn mà CLIENT được phép tự khai (?via=). Các nguồn khác chỉ backend đặt.
CLIENT_SOURCES = ("app", "widget", "shortcut")

RETENTION_DAYS = 90

_PURIFIER_MODES = {"1": "Lọc Thấp", "2": "Lọc TB", "3": "Lọc Cao", "auto": "Lọc Auto", "sleep": "Lọc Ngủ"}
_DOOR_MODES = {"open": "Mở", "close": "Đóng", "stop": "Dừng"}

# device_id -> monotonic lúc HỆ THỐNG gửi lệnh gần nhất. Dùng để không nhầm
# hậu quả của chính lệnh mình với "thay đổi từ bên ngoài" (xem device_history).
_last_sent: dict[str, float] = {}


def now_ms() -> int:
    return int(time.time() * 1000)


def action_label(device, action_type: Optional[str], action_value: Optional[str]) -> str:
    """Nhãn tiếng Việt cho 1 hành động, theo LOẠI thiết bị."""
    if action_type in ("on", "turn_on"):
        return "Bật"
    if action_type in ("off", "turn_off"):
        return "Tắt"
    value = str(action_value or "")
    kind = device_kind(device) if device is not None else None
    if value in _DOOR_MODES and kind in ("curtain", None):
        return _DOOR_MODES[value]
    if kind == "feeder" and value.isdigit():
        return f"Cho ăn {value} phần"
    if kind == "purifier" and value in _PURIFIER_MODES:
        return _PURIFIER_MODES[value]
    return f"Chế độ {value}" if value else (action_type or "?")


def member_name(member) -> Optional[str]:
    if member is None:
        return None
    name = (getattr(member, "display_name", None) or "").strip()
    if name:
        return name
    email = getattr(member, "email", None) or ""
    return email.split("@")[0] or getattr(member, "user_id", None)


def mark_sent(device_id: str) -> None:
    _last_sent[device_id] = time.monotonic()


def recently_sent(device_id: str, within_seconds: float) -> bool:
    ts = _last_sent.get(device_id)
    return ts is not None and (time.monotonic() - ts) < within_seconds


async def record(
    db: AsyncSession,
    *,
    device,
    device_id: Optional[str] = None,
    action_type: Optional[str],
    action_value: Optional[str],
    source: str,
    success: Optional[bool],
    member=None,
    detail: Optional[str] = None,
) -> None:
    """Ghi 1 lệnh do hệ thống gửi. `device` là hàng DeviceModel (có thể None nếu đã bị xóa)."""
    dev_id = device_id or getattr(device, "id", None)
    if not dev_id:
        return
    mark_sent(dev_id)
    try:
        db.add(CommandLogModel(
            at_ms=now_ms(),
            device_id=dev_id,
            device_name=getattr(device, "name", None),
            action_type=action_type,
            action_value=action_value,
            action_label=action_label(device, action_type, action_value),
            source=source,
            user_id=getattr(member, "user_id", None),
            user_name=member_name(member),
            success=success,
            detail=(detail or None) and str(detail)[:300],
        ))
        await db.commit()
    except Exception as e:  # lịch sử hỏng không được kéo lệnh hỏng theo
        logger.warning(f"Không ghi được lịch sử lệnh {dev_id}: {e}")
        try:
            await db.rollback()
        except Exception:
            pass


async def prune_old(db: AsyncSession, days: int = RETENTION_DAYS) -> int:
    """Xóa lịch sử cũ hơn `days` ngày (bảng không phình mãi trên Supabase free)."""
    cutoff = now_ms() - days * 86_400_000
    n = (await db.execute(
        delete(CommandLogModel).where(CommandLogModel.at_ms < cutoff)
        .execution_options(synchronize_session=False)
    )).rowcount
    await db.commit()
    return n
