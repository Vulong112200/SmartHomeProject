"""
ĐIỀU KIỆN của kịch bản: kiểm tra TRƯỚC khi gửi bất kỳ lệnh nào.

Schema lưu ở `scenes.conditions` (JSON text, NULL = không có điều kiện):

    {
      "operator": "AND" | "OR",
      "items": [
        {"type": "time_range", "start": "22:00", "end": "06:00",
         "timezone": "Asia/Ho_Chi_Minh"},
        {"type": "device_state", "device_id": "<id thật>", "expected_state": "off"}
      ]
    }

Kết quả đánh giá là logic BA GIÁ TRỊ: passed | failed | unknown.
  AND: có failed -> failed; còn lại có unknown -> unknown; hết -> passed.
  OR:  có passed -> passed; còn lại có unknown -> unknown; hết -> failed.
Chỉ `passed` mới được chạy hành động — unknown (offline, lỗi đọc, không có
quyền, thiết bị đã xóa) KHÔNG BAO GIỜ được coi là đạt.

Module này sạch HTTP/DB: quyền và cách đọc trạng thái do main.py truyền vào
(`get_device`, `visible_devices`, `read_state`) — core/household.py vẫn là nơi
duy nhất quyết định quyền.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from app.models.device import device_kind

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
MAX_CONDITIONS = 10
STATE_READ_TIMEOUT = 12.0  # giây/thiết bị; app chờ /run tối đa 40s

PASSED, FAILED, UNKNOWN, NOT_EVALUATED = "passed", "failed", "unknown", "not_evaluated"
OPERATORS = ("AND", "OR")

# Trạng thái mong muốn hợp lệ theo LOẠI (models/device.device_kind). Máy cho ăn
# KHÔNG có: "ON" của nó chỉ nghĩa là đang online, không phải đang bật.
EXPECTED_STATES: dict[str | None, tuple[str, ...]] = {
    "purifier": ("on", "off"),
    "switch": ("on", "off"),
    None: ("on", "off"),
    "curtain": ("open", "closed"),
}

_STATE_LABELS = {
    "on": "đang bật", "off": "đang tắt", "open": "đang mở", "closed": "đang đóng",
    "partial": "đang mở dở",
}

# door_state của connector Tuya -> trạng thái quan sát. "opening/closing" = đang
# chạy, "stopped" = lệnh cuối là dừng (không biết dừng ở đâu) => không xác định.
_DOOR_OBSERVED = {
    "open": "open", "closed": "closed", "partial": "partial",
    "opening": "moving", "closing": "moving", "stopped": None, "unknown": None,
}

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")

SKIP_MESSAGES = {
    FAILED: "Kịch bản đã bỏ qua: Không thỏa mãn điều kiện thực thi.",
    UNKNOWN: "Kịch bản đã bỏ qua: Không xác định được điều kiện thực thi.",
}


# =========================================================
# Chuẩn hóa lúc LƯU (POST/PATCH /api/scenes)
# =========================================================
def _parse_hhmm(value: Any) -> int | None:
    """'HH:MM' -> số phút trong ngày; sai định dạng -> None."""
    m = _HHMM.match(str(value or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        raise ValueError(f"Múi giờ không hợp lệ: {name}")


def _normalize_time_range(item: dict) -> dict:
    start, end = _parse_hhmm(item.get("start")), _parse_hhmm(item.get("end"))
    if start is None or end is None:
        raise ValueError("Giờ phải có dạng HH:MM (00:00–23:59).")
    # Quy tắc: bắt đầu TÍNH, kết thúc KHÔNG tính; trùng nhau là mơ hồ (0 phút
    # hay cả ngày?) => từ chối, không đoán.
    if start == end:
        raise ValueError("Giờ bắt đầu và giờ kết thúc phải khác nhau.")
    tz = str(item.get("timezone") or DEFAULT_TIMEZONE)
    _zone(tz)
    return {"type": "time_range", "start": _fmt(start), "end": _fmt(end), "timezone": tz}


def _normalize_device_state(item: dict, get_device: Callable[[str], Any]) -> dict:
    device_id = str(item.get("device_id") or "").strip()
    if not device_id:
        raise ValueError("Điều kiện thiết bị thiếu device_id.")
    device = get_device(device_id)  # 404/403 của household đi thẳng ra ngoài
    allowed = EXPECTED_STATES.get(device_kind(device))
    if allowed is None:
        raise ValueError(f"{device.name}: không dùng làm điều kiện được (không có trạng thái bật/tắt).")
    expected = str(item.get("expected_state") or "").strip().lower()
    if expected not in allowed:
        raise ValueError(f"{device.name}: trạng thái mong muốn phải là {' / '.join(allowed)}.")
    return {"type": "device_state", "device_id": device.id, "expected_state": expected}


def normalize_conditions(raw: Any, get_device: Callable[[str], Any]) -> dict | None:
    """
    Kiểm + chuẩn hóa điều kiện client gửi. Trả None khi không có điều kiện nào
    (lưu NULL — giống hệt kịch bản cũ). Sai -> ValueError (tiếng Việt).
    `get_device(id)` phải trả thiết bị NGƯỜI LƯU được dùng, hoặc ném lỗi.
    Nhận cả list trần (= AND) cho tiện.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = {"operator": "AND", "items": raw}
    if not isinstance(raw, dict):
        raise ValueError("Điều kiện phải có dạng {operator, items}.")
    operator = str(raw.get("operator") or "AND").strip().upper()
    if operator not in OPERATORS:
        raise ValueError("Cách kết hợp phải là AND hoặc OR.")
    items = raw.get("items") or []
    if not isinstance(items, list):
        raise ValueError("items phải là danh sách.")
    if len(items) > MAX_CONDITIONS:
        raise ValueError(f"Tối đa {MAX_CONDITIONS} điều kiện.")
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Mỗi điều kiện phải là một object.")
        kind = item.get("type")
        if kind == "time_range":
            out.append(_normalize_time_range(item))
        elif kind == "device_state":
            out.append(_normalize_device_state(item, get_device))
        else:
            raise ValueError(f"Loại điều kiện không hỗ trợ: {kind}")
    return {"operator": operator, "items": out} if out else None


def load_stored(text: str | None) -> tuple[dict | None, bool]:
    """
    Đọc cột `scenes.conditions` -> (điều kiện | None, hỏng?). Dữ liệu hỏng
    (không phải do API ghi) KHÔNG được coi là "không có điều kiện" — gọi ở
    luồng chạy phải xem hỏng = unknown, để kịch bản không chạy mù.
    """
    if text in (None, ""):
        return None, False
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None, True
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None, True
    if not data["items"]:
        return None, False
    return data, False


def empty_conditions() -> dict:
    return {"operator": "AND", "items": []}


# =========================================================
# Đánh giá lúc CHẠY
# =========================================================
def time_in_range(now_minutes: int, start: int, end: int) -> bool:
    """[start, end) theo phút trong ngày; start > end = qua đêm (22:00→06:00)."""
    if start < end:
        return start <= now_minutes < end
    return now_minutes >= start or now_minutes < end


def _result(item: dict, result: str, reason: str) -> dict:
    return {**item, "result": result, "reason": reason}


def _eval_time(item: dict, now: datetime | None) -> dict:
    start, end = _parse_hhmm(item.get("start")), _parse_hhmm(item.get("end"))
    if start is None or end is None or start == end:
        return _result(item, UNKNOWN, "Điều kiện giờ không hợp lệ")
    try:
        zone = _zone(str(item.get("timezone") or DEFAULT_TIMEZONE))
    except ValueError as e:
        return _result(item, UNKNOWN, str(e))
    # Không phụ thuộc giờ của máy chủ: luôn quy đổi sang múi giờ của điều kiện.
    local = now.astimezone(zone) if now is not None else datetime.now(zone)
    minutes = local.hour * 60 + local.minute
    window = f"{_fmt(start)}–{_fmt(end)}"
    if time_in_range(minutes, start, end):
        return _result(item, PASSED, f"Trong khung giờ {window}")
    return _result(item, FAILED, f"Ngoài khung giờ {window} (bây giờ {_fmt(minutes)})")


def observed_state(kind: str | None, state: Any) -> str | None:
    """
    Trạng thái connector -> 'on' | 'off' | 'open' | 'closed' | 'partial' |
    'moving' | 'offline' | None (không xác định). Offline KHÔNG BAO GIỜ thành 'off'.
    """
    if not isinstance(state, dict):
        return None
    status = str(state.get("status") or "")
    if status.lower() == "offline":
        return "offline"
    if kind == "curtain":
        return _DOOR_OBSERVED.get(str(state.get("door_state") or "unknown").lower())
    if status == "ON":
        return "on"
    if status == "OFF":
        return "off"
    return None


async def _eval_device(item: dict, visible_devices: dict, known_ids: set,
                       read_state: Callable[[Any], Awaitable[dict]]) -> dict:
    device_id = item.get("device_id")
    device = visible_devices.get(device_id)
    if device is None:
        # Không đọc trạng thái thiết bị ngoài quyền của người chạy: vừa lộ thông
        # tin, vừa thành cách "mượn" thiết bị khác để vượt phân quyền.
        if device_id in known_ids:
            return _result(item, UNKNOWN, "Bạn không có quyền với thiết bị trong điều kiện")
        return _result(item, UNKNOWN, "Thiết bị trong điều kiện không còn tồn tại")

    kind = device_kind(device)
    expected = item.get("expected_state")
    if expected not in EXPECTED_STATES.get(kind, ()):
        return _result(item, UNKNOWN, f"Điều kiện không còn hợp lệ với loại thiết bị {device.name}")

    try:
        state = await asyncio.wait_for(read_state(device), STATE_READ_TIMEOUT)
    except asyncio.TimeoutError:
        return _result(item, UNKNOWN, f"Không đọc được trạng thái {device.name} (quá thời gian)")
    except Exception:
        return _result(item, UNKNOWN, f"Không đọc được trạng thái {device.name}")

    observed = observed_state(kind, state)
    if observed == "offline":
        return _result(item, UNKNOWN, f"{device.name} đang offline")
    if observed == "moving":
        return _result(item, UNKNOWN, f"{device.name} đang chạy, chưa tới vị trí")
    if observed is None:
        return _result(item, UNKNOWN, f"Chưa xác định được trạng thái {device.name}")
    label = f"{device.name} {_STATE_LABELS.get(observed, observed)}"
    if observed == expected:
        return _result(item, PASSED, label)
    return _result(item, FAILED, f"{label} (cần {_STATE_LABELS.get(expected, expected)})")


def combine(operator: str, results: list[str]) -> str:
    """Gộp ba giá trị theo AND/OR (Kleene). Danh sách rỗng = passed."""
    if not results:
        return PASSED
    if operator == "OR":
        if PASSED in results:
            return PASSED
        return UNKNOWN if UNKNOWN in results else FAILED
    if FAILED in results:
        return FAILED
    return UNKNOWN if UNKNOWN in results else PASSED


def _decided(operator: str, results: list[str]) -> bool:
    """Đã biết kết quả mà không cần đọc thiết bị (tiết kiệm quota Tuya)?"""
    return (operator == "AND" and FAILED in results) or (operator == "OR" and PASSED in results)


async def evaluate_conditions(
    conditions: dict | None,
    *,
    visible_devices: dict,
    known_ids: set,
    read_state: Callable[[Any], Awaitable[dict]],
    now: datetime | None = None,
) -> dict:
    """
    -> {"result", "operator", "reason", "items": [{...điều kiện, result, reason}]}
    `visible_devices` = thiết bị NGƯỜI CHẠY dùng được (device_query);
    `known_ids` = mọi id thiết bị trong nhà (để báo đúng lý do);
    `read_state(device)` phải đọc TRẠNG THÁI MỚI (không dùng cache).
    """
    if not conditions or not conditions.get("items"):
        return {"result": PASSED, "operator": "AND", "reason": "Không có điều kiện", "items": []}

    operator = str(conditions.get("operator") or "AND").upper()
    if operator not in OPERATORS:
        operator = "AND"
    items = conditions["items"]
    results: list[dict | None] = [None] * len(items)

    # Điều kiện giờ trước (rẻ) — nếu đã đủ kết luận thì khỏi gọi cloud.
    for i, item in enumerate(items):
        kind = item.get("type") if isinstance(item, dict) else None
        if kind == "time_range":
            results[i] = _eval_time(item, now)
        elif kind != "device_state":
            results[i] = _result(item if isinstance(item, dict) else {}, UNKNOWN, "Loại điều kiện không hỗ trợ")

    pending = [i for i, r in enumerate(results) if r is None]
    if pending and not _decided(operator, [r["result"] for r in results if r]):
        # Chỉ ĐỌC trạng thái — song song được, không như hành động (tuần tự).
        evaluated = await asyncio.gather(*(
            _eval_device(items[i], visible_devices, known_ids, read_state) for i in pending
        ))
        for i, r in zip(pending, evaluated):
            results[i] = r
    else:
        for i in pending:
            results[i] = _result(items[i], NOT_EVALUATED, "Không cần kiểm tra")

    overall = combine(operator, [r["result"] for r in results if r["result"] != NOT_EVALUATED])
    if overall == PASSED:
        reason = "Đủ điều kiện"
    else:
        reason = "; ".join(r["reason"] for r in results if r["result"] == overall)
    return {"result": overall, "operator": operator, "reason": reason, "items": results}


def broken_result() -> dict:
    """Điều kiện lưu trong DB hỏng -> không chạy (unknown), không bao giờ coi như rỗng."""
    return {"result": UNKNOWN, "operator": "AND", "reason": "Điều kiện đã lưu bị hỏng — hãy sửa lại kịch bản",
            "items": []}
