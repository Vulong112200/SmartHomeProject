from .vn_time_parser import extract_schedule_times

# Từ khóa "mồi" theo brand — dùng khi đuôi câu khoảng ("... đến 17h30 chuyển mức TB")
# không nhắc lại thiết bị: ghép mồi vào để tái dùng logic trích hành động sẵn có.
_BRAND_HINT = {"vesync": "máy lọc", "tuya": "cửa", "rojeco": "cho ăn"}


def _extract_device_actions(text: str, devices_list: list) -> list:
    """
    Trích (thiết bị, hành động) bằng keyword matching — logic gốc của local parser.
    Trả về list {"brand","id","action","mode"} với action kiểu turn_on/turn_off/set_mode.
    """
    text = text.lower()
    actions = []

    # 1. MÁY LỌC KHÔNG KHÍ (VeSync)
    # Từ khóa nhận diện: lọc, quạt, máy khí, không khí
    if any(kw in text for kw in ["lọc", "quạt", "không khí", "máy khí"]):
        vesync_id = next((d.id for d in devices_list if d.brand == "vesync"), None)
        if vesync_id:
            # TẮT
            if any(kw in text for kw in ["tắt", "đóng", "off", "ngừng"]):
                actions.append({"brand": "vesync", "id": vesync_id, "action": "turn_off", "mode": None})

            # CÁC CHẾ ĐỘ (Ưu tiên kiểm tra chế độ trước)
            elif any(kw in text for kw in ["tự động", "auto", "thông minh"]):
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "auto"})
            elif any(kw in text for kw in ["ngủ", "sleep", "đêm", "ban đêm", "im lặng"]):
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "sleep"})
            elif any(kw in text for kw in ["thấp", "nhỏ", "nhẹ", "số 1", "mức 1", "yếu"]):
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "1"})
            elif any(kw in text for kw in ["trung bình", "vừa", "số 2", "mức 2"]):
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "2"})
            elif any(kw in text for kw in ["cao", "mạnh", "lớn", "số 3", "mức 3", "max", "tối đa"]):
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "3"})

            # BẬT (Nếu không nói rõ chế độ, mặc định chỉ bật lên)
            elif any(kw in text for kw in ["bật", "mở", "chạy", "khởi động", "on"]):
                actions.append({"brand": "vesync", "id": vesync_id, "action": "turn_on", "mode": None})

    # 2. MÁY CHO MÈO ĂN (Rojeco)
    # Từ khóa: mèo, chó, ăn, hạt, đói
    if any(kw in text for kw in ["mèo", "chó", "ăn", "hạt", "đói"]):
        rojeco_id = next((d.id for d in devices_list if d.brand == "rojeco"), None)
        if rojeco_id:
            mode = "1" # Mặc định là 1 phần nếu không nói rõ
            if any(kw in text for kw in ["2 phần", "hai phần", "nhiều chút", "vừa vừa"]): mode = "2"
            if any(kw in text for kw in ["3 phần", "ba phần", "nhiều", "đầy", "max"]): mode = "3"

            actions.append({"brand": "rojeco", "id": rojeco_id, "action": "set_mode", "mode": mode})

    # 3. CỬA CUỐN (Tuya)
    # Từ khóa: cửa, cuốn, rèm
    if any(kw in text for kw in ["cửa", "cuốn", "rèm"]):
        tuya_id = next((d.id for d in devices_list if d.brand == "tuya"), None)
        if tuya_id:
            if any(kw in text for kw in ["mở", "lên", "kéo lên"]):
                actions.append({"brand": "tuya", "id": tuya_id, "action": "set_mode", "mode": "open"})
            elif any(kw in text for kw in ["đóng", "xuống", "kéo xuống", "sập"]):
                actions.append({"brand": "tuya", "id": tuya_id, "action": "set_mode", "mode": "close"})
            elif any(kw in text for kw in ["dừng", "stop", "đứng", "ngưng"]):
                actions.append({"brand": "tuya", "id": tuya_id, "action": "set_mode", "mode": "stop"})

    return actions


def _default_end_action(start: dict):
    """
    Hành động kết thúc MẶC ĐỊNH khi câu khoảng chỉ nói 1 hành động:
    - Cửa tuya đang MỞ -> đóng lại; cửa đóng/dừng thì KHÔNG đoán (an toàn: không tự mở cửa).
    - Còn lại (máy lọc, máy cho ăn...) -> tắt.
    Trả về (end_action, end_mode) hoặc None nếu không có mặc định an toàn.
    """
    if start["brand"] == "tuya":
        if start.get("mode") == "open":
            return "set_mode", "close"
        return None
    return "turn_off", None


def parse_command_locally(text: str, devices_list: list) -> list:
    """
    Hệ thống phân tích lệnh nội bộ siêu tốc.
    Bao quát các từ đồng nghĩa, từ lóng tiếng Việt.

    Câu CÓ mốc giờ ("hẹn 16 giờ 30...", "từ 16h30 đến 17h30...") -> ý định HẸN GIỜ:
    chỉ trả {"intent": "schedule", ...} (hoặc [] để AI thử) — TUYỆT ĐỐI không trả
    action thi hành ngay, tránh "hẹn 16h30 bật quạt" mà quạt bật luôn.
    """
    text = text.lower()
    sched = extract_schedule_times(text)
    if sched is None:
        return _extract_device_actions(text, devices_list)  # đường cũ: thi hành ngay

    # ----- Ý ĐỊNH HẸN GIỜ -----
    device_actions = _extract_device_actions(sched["cleaned_text"], devices_list)
    if not device_actions:
        return []  # có giờ nhưng không rõ thiết bị/hành động -> để AI fallback thử

    start = device_actions[0]
    end_action = end_mode = None
    if sched["end"]:
        # Best-effort 2 hành động: "16h30 bật quạt mức cao, đến 17h30 chuyển mức TB"
        # -> đầu câu và đuôi câu mỗi bên 1 hành động cho CÙNG thiết bị.
        head_acts = _extract_device_actions(sched["cleaned_head"] or "", devices_list)
        tail_acts = _extract_device_actions(sched["cleaned_tail"] or "", devices_list)
        if not tail_acts and sched["cleaned_tail"]:
            hint = _BRAND_HINT.get(start["brand"], "")
            tail_acts = [a for a in _extract_device_actions(f"{hint} {sched['cleaned_tail']}", devices_list)
                         if a["brand"] == start["brand"]]
        if head_acts and tail_acts and head_acts[0]["brand"] == tail_acts[0]["brand"]:
            start = head_acts[0]
            end_action, end_mode = tail_acts[0]["action"], tail_acts[0]["mode"]
        else:
            default = _default_end_action(start)
            if default:
                end_action, end_mode = default

    result = {
        "intent": "schedule",
        "brand": start["brand"], "id": start["id"],
        "action": start["action"], "mode": start["mode"],
        "time": sched["start"],
        "end_time": sched["end"] if end_action else None,  # không có end action an toàn -> lịch đơn
        "end_action": end_action, "end_mode": end_mode,
        "day_offset": sched["day_offset"],
        "recurring_daily": sched["recurring_daily"],
    }
    return [result]
