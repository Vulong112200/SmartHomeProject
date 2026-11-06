"""
Ghi nhận thay đổi KHÔNG đến từ hệ thống này: nút vật lý, công tắc tường, app
Smart Life/VeSync, lịch cài sẵn trong máy.

Thiết bị Tuya (cửa cuốn, máy bơm, máy cho ăn Rojeco) — đọc NHẬT KÝ Tuya Cloud
`GET /v1.0/devices/{id}/logs` (đã kiểm với thiết bị thật 2026-11-05):
  - type=5 "lệnh gửi tới thiết bị", `event_from`:
        "cloud2cloud" = backend này (đã tự ghi lúc gửi, có tên người) -> bỏ qua
        "2"           = app Smart Life/Tuya trên điện thoại            -> `tuya_app`
        khác          = nền tảng khác (trợ lý ảo...)                    -> `external`
  - type=7 "thiết bị báo trạng thái" (event_from luôn "1"): nếu KHÔNG có lệnh
    type=5 cùng thiết bị ngay trước đó => thay đổi phát sinh TẠI thiết bị (nút
    vật lý / công tắc tường / lịch trong máy) -> `device`.
  ⚠️ Remote RF điều khiển thẳng motor cửa thì cloud không biết => không có ở đây.

Máy lọc VeSync không có nhật ký: so trạng thái mỗi lần backend đọc từ máy,
đổi mà hệ thống không vừa gửi lệnh => `external`. Chỉ thấy được khi có người
đang mở app (app poll trạng thái), và thời điểm là lúc PHÁT HIỆN.
"""
import asyncio
import logging
import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.command_log import CommandLogModel
from app.models.device import device_kind

from .command_log import action_label, now_ms, prune_old, recently_sent
from .connector_manager import device_manager

logger = logging.getLogger(__name__)

_TUYA_BRANDS = ("tuya", "rojeco")
# Chỉ DP có ý nghĩa với người dùng (máy bơm còn báo `remote_list` mỗi sáng — nhiễu).
_TUYA_CODES = ("control", "switch_1", "manual_feed", "feed_report")
_LOOKBACK_MS = 7 * 86_400_000         # nhật ký Tuya giữ ~7 ngày
_SYNC_EVERY_SECONDS = 60              # mở màn lịch sử liên tục không đốt quota Tuya
_ECHO_MS = {"feeder": 180_000}        # nhả hạt xong mới báo feed_report
_DEFAULT_ECHO_MS = 20_000             # cửa/công tắc báo lại trong vài giây
_VESYNC_ECHO_SECONDS = 60

_last_sync: dict[str, float] = {}
_last_prune: list[float] = [0.0]
_vesync_seen: dict[str, tuple] = {}

_DEVICE_DETAIL = {
    "curtain": "Tại cửa: nút vật lý / công tắc tường",
    "switch": "Tại thiết bị: công tắc / nút trên máy",
    "feeder": "Tại máy: lịch cài trong máy hoặc nút trên máy",
}


def _event_label(device, code: str, value) -> str:
    v = str(value).lower()
    if code == "switch_1":
        return "Bật" if v == "true" else "Tắt"
    if code == "feed_report":
        return f"Đã cho ăn {value} phần"
    if code == "manual_feed":
        return f"Cho ăn {value} phần"
    return action_label(device, "mode", v)


def classify_tuya_logs(device, commands: list[dict], reports: list[dict]) -> list[dict]:
    """
    Gộp nhật ký type=5 (`commands`) + type=7 (`reports`) thành các sự kiện cần ghi.
    Hàm THUẦN (không gọi mạng/DB) để test được. Trả list dict cho CommandLogModel.
    """
    kind = device_kind(device)
    echo_ms = _ECHO_MS.get(kind, _DEFAULT_ECHO_MS)
    events = []
    cmd_times = sorted(int(c["event_time"]) for c in commands if c.get("code") in _TUYA_CODES)

    for c in commands:
        code, src = c.get("code"), str(c.get("event_from", ""))
        if code not in _TUYA_CODES or src == "cloud2cloud":
            continue
        t = int(c["event_time"])
        events.append(dict(
            at_ms=t, action_type="event", action_value=str(c.get("value")),
            action_label=_event_label(device, code, c.get("value")),
            source="tuya_app" if src == "2" else "external",
            detail="App Smart Life / Tuya" if src == "2" else f"Nền tảng khác (event_from={src})",
            ext_id=f"tuya:{device.id}:5:{t}:{code}",
        ))

    for r in reports:
        code = r.get("code")
        if code not in _TUYA_CODES:
            continue
        t = int(r["event_time"])
        if any(t - echo_ms <= ct <= t for ct in cmd_times):
            continue  # báo lại kết quả của 1 lệnh đã biết nguồn
        detail = _DEVICE_DETAIL.get(kind, "Tại thiết bị")
        if code == "control" and str(r.get("value")) == "stop":
            detail += " (hoặc cửa tự dừng ở cuối hành trình)"
        events.append(dict(
            at_ms=t, action_type="event", action_value=str(r.get("value")),
            action_label=_event_label(device, code, r.get("value")),
            source="device", detail=detail,
            ext_id=f"tuya:{device.id}:7:{t}:{code}",
        ))
    return events


async def _insert_events(db: AsyncSession, device, events: list[dict]) -> int:
    if not events:
        return 0
    ids = [e["ext_id"] for e in events]
    known = set((await db.execute(
        select(CommandLogModel.ext_id).where(CommandLogModel.ext_id.in_(ids))
    )).scalars().all())
    added = 0
    for e in events:
        if e["ext_id"] in known:
            continue
        db.add(CommandLogModel(device_id=device.id, device_name=device.name, success=None, **e))
        known.add(e["ext_id"])
        added += 1
    await db.commit()
    return added


async def _fetch_tuya_events(device) -> list[dict] | None:
    """Gọi mạng (KHÔNG đụng DB) — chạy song song cho nhiều thiết bị được."""
    connector = device_manager.get_connector(device.brand)
    fetch = getattr(connector, "fetch_event_logs", None)
    if fetch is None:
        return None
    end = now_ms()
    start = end - _LOOKBACK_MS
    commands, reports = await asyncio.gather(
        fetch(device.id, 5, start, end), fetch(device.id, 7, start, end),
    )
    if commands is None or reports is None:
        return None  # lỗi mạng / hết quota: lần sau thử lại, không ghi nửa vời
    return classify_tuya_logs(device, commands, reports)


async def sync_external_events(db: AsyncSession, devices: list) -> int:
    """
    Đồng bộ nhật ký Tuya cho các thiết bị (mỗi thiết bị tối đa 1 lần/60s).
    Gọi cloud SONG SONG, ghi DB TUẦN TỰ: một AsyncSession không được dùng đồng
    thời từ nhiều task; và không giữ transaction trong lúc chờ cloud.
    """
    now = time.monotonic()
    due = [d for d in devices
           if d.brand in _TUYA_BRANDS and now - _last_sync.get(d.id, -1e9) >= _SYNC_EVERY_SECONDS]
    for d in due:
        _last_sync[d.id] = now
    results = await asyncio.gather(*(_fetch_tuya_events(d) for d in due), return_exceptions=True)
    added = 0
    for d, r in zip(due, results):
        try:
            if isinstance(r, BaseException):
                raise r
            if r:
                added += await _insert_events(db, d, r)
        except Exception as e:
            logger.warning(f"Đồng bộ nhật ký {d.brand}/{d.id} lỗi: {e}")
            _last_sync.pop(d.id, None)
            await _safe_rollback(db)
    if now - _last_prune[0] > 86_400:
        _last_prune[0] = now
        try:
            await prune_old(db)
        except Exception as e:
            logger.warning(f"Dọn lịch sử cũ lỗi: {e}")
            await _safe_rollback(db)
    return added


async def _safe_rollback(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


def _vesync_key(state: dict) -> Optional[tuple]:
    status = state.get("status")
    if status not in ("ON", "OFF"):
        return None  # offline / lỗi đọc: không phải thay đổi của người dùng
    if status == "OFF":
        return ("OFF",)
    return ("ON", str(state.get("mode") or ""), str(state.get("speed") or ""))


def _vesync_label(key: tuple) -> str:
    if key[0] == "OFF":
        return "Tắt"
    _, mode, speed = key
    if mode == "manual" and speed in ("1", "2", "3"):
        return {"1": "Lọc Thấp", "2": "Lọc TB", "3": "Lọc Cao"}[speed]
    if mode == "auto":
        return "Lọc Auto"
    if mode == "sleep":
        return "Lọc Ngủ"
    return "Bật"


async def _recent_system_command(db: AsyncSession, device_id: str, within_seconds: float) -> bool:
    """
    Có lệnh do HỆ THỐNG gửi (success khác NULL) tới thiết bị này gần đây không —
    đọc từ DB, nên thấy cả lệnh của TIẾN TRÌNH KHÁC (worker hẹn giờ tại nhà),
    thứ `recently_sent` (RAM của tiến trình này) không thấy. Lỗi DB → False
    (thà ghi thừa 1 dòng "ngoài app" còn hơn nuốt mất thay đổi thật).
    """
    try:
        cut = now_ms() - int(within_seconds * 1000)
        return (await db.execute(
            select(CommandLogModel.id).where(
                CommandLogModel.device_id == device_id,
                CommandLogModel.success.isnot(None),
                CommandLogModel.at_ms >= cut,
            ).limit(1)
        )).first() is not None
    except Exception as e:
        logger.warning(f"Không kiểm được lệnh gần đây của {device_id}: {e}")
        await _safe_rollback(db)
        return False


async def observe_state(db: AsyncSession, device, state: dict) -> bool:
    """
    Gọi mỗi lần backend đọc trạng thái THẬT (không phải cache) của máy lọc
    VeSync. Đổi so với lần đọc trước mà hệ thống không vừa gửi lệnh => ghi
    `external`. Trả True nếu đã ghi.
    """
    if device is None or device.brand != "vesync":
        return False
    key = _vesync_key(state or {})
    if key is None:
        return False
    prev = _vesync_seen.get(device.id)
    _vesync_seen[device.id] = key
    if prev is None or prev == key or recently_sent(device.id, _VESYNC_ECHO_SECONDS):
        return False
    if await _recent_system_command(db, device.id, _VESYNC_ECHO_SECONDS):
        return False
    try:
        db.add(CommandLogModel(
            at_ms=now_ms(), device_id=device.id, device_name=device.name,
            action_type="event", action_value="/".join(key), action_label=_vesync_label(key),
            source="external", success=None,
            detail="Ngoài app: nút trên máy hoặc app VeSync (thời điểm = lúc phát hiện)",
        ))
        await db.commit()
        return True
    except Exception as e:
        logger.warning(f"Không ghi được thay đổi ngoài app {device.id}: {e}")
        await _safe_rollback(db)
        return False
