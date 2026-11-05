# backend/app/services/floor_plan.py
"""
Sơ đồ mặt bằng 2D — dữ liệu thuần, không đụng DB/quyền (quyền ở core/household.py,
endpoint ở main.py).

Đơn vị: MÉT. Hệ trục: x sang phải, y xuống dưới, gốc tùy ý (app tự tính khung bao).

    rooms:   [{id, name, width, depth, x, y}]   x,y = góc trên-trái của phòng trên sơ đồ
    doors:   [{id, room, wall, offset, width}]  wall ∈ top|bottom|left|right;
                                                offset = mét tính từ đầu tường
                                                (trái với top/bottom, trên với left/right)
    devices: [{device_id, room, x, y}]          x,y = mét TÍNH TỪ góc trên-trái của PHÒNG

Lưu theo mét trong phòng (không theo pixel / phần trăm màn hình) ⇒ đổi điện
thoại, xoay màn hình, zoom hay đổi kích thước phòng không làm thiết bị "trôi".
"""
import json
import math
import re

# Kích thước THẬT do chủ nhà đo. Vị trí tương đối 2 phòng + cửa CHƯA biết ⇒
# mặc định đặt cạnh nhau, không có cửa; `configured: false` để app nhắc chủ nhà
# vào "Sửa sơ đồ" kéo phòng / thêm cửa cho đúng thực tế (không tự đoán).
DEFAULT_LAYOUT = {
    "rooms": [
        {"id": "main", "name": "Phòng chính", "width": 4.09, "depth": 3.00, "x": 0.0, "y": 0.0},
        {"id": "bath", "name": "Phòng tắm", "width": 2.17, "depth": 3.06, "x": 4.09, "y": 0.0},
    ],
    "doors": [],
    "devices": [],
}

WALLS = ("top", "bottom", "left", "right")

MAX_ROOMS = 12
MAX_DOORS = 40
MAX_DEVICES = 500
MAX_ID_LEN = 128

ROOM_SIZE_RANGE = (0.5, 50.0)      # m
ROOM_POS_RANGE = (-200.0, 200.0)   # m
DOOR_WIDTH_RANGE = (0.3, 6.0)      # m
_EPS = 1e-6

_ROOM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def default_layout() -> dict:
    """Bản sao (không trả hằng số để caller lỡ sửa cũng không hỏng mặc định)."""
    return json.loads(json.dumps(DEFAULT_LAYOUT))


def _num(value, what: str, lo: float, hi: float) -> float:
    # bool là int trong Python — chặn để `true` không thành 1.0 mét.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} phải là số.")
    v = float(value)
    if not math.isfinite(v) or v < lo - _EPS or v > hi + _EPS:
        raise ValueError(f"{what} phải trong khoảng {lo:g}–{hi:g} m.")
    return round(min(max(v, lo), hi), 3)


def _list(raw: dict, key: str, limit: int) -> list:
    items = raw.get(key, [])
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError(f"'{key}' phải là danh sách.")
    if len(items) > limit:
        raise ValueError(f"Quá nhiều mục trong '{key}' (tối đa {limit}).")
    for it in items:
        if not isinstance(it, dict):
            raise ValueError(f"Mỗi mục trong '{key}' phải là object.")
    return items


def _wall_length(room: dict, wall: str) -> float:
    return room["width"] if wall in ("top", "bottom") else room["depth"]


def sanitize_layout(raw, known_device_ids: set[str]) -> dict:
    """
    Kiểm + làm sạch sơ đồ client gửi lên. Ném ValueError (thông báo tiếng Việt)
    khi hình học sai — sơ đồ hỏng thì chủ nhà phải biết, không lưu nửa vời.

    Riêng thiết bị: id không còn trong nhà / trùng bị BỎ ÂM THẦM (thiết bị có
    thể vừa bị xóa giữa lúc kéo và lúc lưu — giống sanitize_device_order), tọa
    độ lệch ra ngoài phòng do làm tròn được kẹp lại vào trong phòng.
    """
    if not isinstance(raw, dict):
        raise ValueError("Sơ đồ phải là object JSON.")

    rooms: list[dict] = []
    room_by_id: dict[str, dict] = {}
    for r in _list(raw, "rooms", MAX_ROOMS):
        rid = r.get("id")
        if not isinstance(rid, str) or not _ROOM_ID_RE.match(rid):
            raise ValueError("Mã phòng không hợp lệ (1-32 ký tự chữ/số/_/-).")
        if rid in room_by_id:
            raise ValueError(f"Trùng mã phòng '{rid}'.")
        name = r.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not 1 <= len(name) <= 40:
            raise ValueError("Tên phòng phải từ 1 đến 40 ký tự.")
        room = {
            "id": rid,
            "name": name,
            "width": _num(r.get("width"), f"Chiều rộng '{name}'", *ROOM_SIZE_RANGE),
            "depth": _num(r.get("depth"), f"Chiều dài '{name}'", *ROOM_SIZE_RANGE),
            "x": _num(r.get("x", 0), f"Vị trí x '{name}'", *ROOM_POS_RANGE),
            "y": _num(r.get("y", 0), f"Vị trí y '{name}'", *ROOM_POS_RANGE),
        }
        rooms.append(room)
        room_by_id[rid] = room
    if not rooms:
        raise ValueError("Sơ đồ phải có ít nhất 1 phòng.")

    doors: list[dict] = []
    door_ids: set[str] = set()
    for d in _list(raw, "doors", MAX_DOORS):
        did = d.get("id")
        if not isinstance(did, str) or not 1 <= len(did) <= 64:
            raise ValueError("Mã cửa không hợp lệ.")
        if did in door_ids:
            raise ValueError(f"Trùng mã cửa '{did}'.")
        room = room_by_id.get(d.get("room"))
        if room is None:
            raise ValueError("Cửa gắn vào phòng không tồn tại.")
        wall = d.get("wall")
        if wall not in WALLS:
            raise ValueError("Tường của cửa phải là top/bottom/left/right.")
        length = _wall_length(room, wall)
        width = _num(d.get("width"), "Bề rộng cửa", *DOOR_WIDTH_RANGE)
        if width > length + _EPS:
            raise ValueError(f"Cửa rộng hơn bức tường của '{room['name']}'.")
        offset = _num(d.get("offset"), "Vị trí cửa", 0.0, length)
        if offset + width > length + _EPS:
            raise ValueError(f"Cửa vượt quá bức tường của '{room['name']}'.")
        door_ids.add(did)
        doors.append({"id": did, "room": room["id"], "wall": wall,
                      "offset": round(min(offset, length - width), 3), "width": width})

    devices: list[dict] = []
    seen: set[str] = set()
    for p in _list(raw, "devices", MAX_DEVICES):
        dev_id = p.get("device_id")
        if not isinstance(dev_id, str) or len(dev_id) > MAX_ID_LEN:
            raise ValueError("Mã thiết bị không hợp lệ.")
        if dev_id not in known_device_ids or dev_id in seen:
            continue
        room = room_by_id.get(p.get("room"))
        if room is None:
            raise ValueError("Thiết bị được đặt vào phòng không tồn tại.")
        x = _num(p.get("x"), "Tọa độ thiết bị", -ROOM_SIZE_RANGE[1], ROOM_SIZE_RANGE[1])
        y = _num(p.get("y"), "Tọa độ thiết bị", -ROOM_SIZE_RANGE[1], ROOM_SIZE_RANGE[1])
        seen.add(dev_id)
        devices.append({
            "device_id": dev_id,
            "room": room["id"],
            "x": round(min(max(x, 0.0), room["width"]), 3),
            "y": round(min(max(y, 0.0), room["depth"]), 3),
        })

    return {"rooms": rooms, "doors": doors, "devices": devices}


def parse_stored(text: str | None) -> dict | None:
    """Đọc layout đã lưu. Hỏng (không phải JSON / thiếu phòng) -> None = dùng mặc định."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("rooms"), list) or not data["rooms"]:
        return None
    data.setdefault("doors", [])
    data.setdefault("devices", [])
    return data


def visible_layout(layout: dict, visible_device_ids: set[str]) -> dict:
    """Bản sơ đồ cho 1 người xem: phòng/cửa giữ nguyên, CHỈ thiết bị người đó thấy."""
    devices = [
        p for p in layout.get("devices") or []
        if isinstance(p, dict) and p.get("device_id") in visible_device_ids
    ]
    return {"rooms": layout["rooms"], "doors": layout.get("doors") or [], "devices": devices}
