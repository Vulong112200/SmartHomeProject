"""
Chuẩn hóa + kiểm tra 1 hành động điều khiển theo LOẠI thiết bị.

Mọi đường điều khiển "không qua UI" (trợ lý AI, lịch tạo bằng giọng nói, kịch
bản) đều đi qua đây trước khi chạm connector. Lý do: hành động đến từ AI/văn
bản tự do — không được tin. Trước đây một action lạ rơi vào nhánh `turn_off`,
tức là ĐÓNG CỬA; còn mode tùy ý tới máy cho ăn là `manual_feed <số bất kỳ>`.
"""
from typing import Optional, Tuple

from app.models.device import device_kind

# Hành động hợp lệ theo loại. Cửa cuốn KHÔNG nhận on/off: "bật tất cả" không
# được phép hiểu thành mở cửa — phải nói rõ mở/đóng/dừng.
# Máy cho ăn chỉ nhận số phần (giới hạn 10 cho an toàn; UI dùng 1-3).
_ALLOWED = {
    "purifier": {"on": True, "off": True, "modes": {"1", "2", "3", "auto", "sleep"}},
    "curtain": {"on": False, "off": False, "modes": {"open", "close", "stop"}},
    "feeder": {"on": False, "off": False, "modes": {str(n) for n in range(1, 11)}},
    "switch": {"on": True, "off": True, "modes": set()},
    None: {"on": True, "off": True, "modes": set()},  # loại chưa rõ: chỉ bật/tắt
}


def normalize_action(device, verb: Optional[str], mode: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Đổi từ vựng parser/AI (turn_on | on | turn_off | off | set_mode | mode, mode
    "on"/"off") -> (action_type ∈ {on, off, mode}, action_value) hợp lệ với
    loại của `device`. Không hợp lệ -> ValueError (thông báo tiếng Việt).
    """
    verb = (verb or "").lower()
    mode = str(mode).lower() if mode not in (None, "") else None
    rules = _ALLOWED.get(device_kind(device), _ALLOWED[None])

    if verb in ("on", "turn_on") or (verb in ("set_mode", "mode", "") and mode == "on"):
        action = ("on", None)
    elif verb in ("off", "turn_off") or (verb in ("set_mode", "mode", "") and mode == "off"):
        action = ("off", None)
    elif verb in ("set_mode", "mode", "") and mode:
        action = ("mode", mode)
    else:
        raise ValueError(f"Hành động không hợp lệ: {verb or '?'}")

    action_type, value = action
    if action_type in ("on", "off") and not rules[action_type]:
        raise ValueError(f"Thiết bị này không hỗ trợ lệnh {'bật' if action_type == 'on' else 'tắt'}")
    if action_type == "mode" and value not in rules["modes"]:
        raise ValueError(f"Chế độ không hợp lệ cho thiết bị này: {value}")
    return action
