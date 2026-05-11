# backend/app/services/local_parser.py

def parse_command_locally(text: str, devices_list: list) -> list:
    """
    Hệ thống phân tích lệnh nội bộ (Không dùng AI).
    Tốc độ cực nhanh, chính xác 100% với các lệnh rõ ràng.
    """
    text = text.lower()
    actions = []

    # 1. BẮT LỆNH MÁY LỌC KHÔNG KHÍ (VeSync)
    if "lọc" in text or "quạt" in text:
        vesync_id = next((d.id for d in devices_list if d.brand == "vesync"), None)
        if vesync_id:
            if "tắt" in text:
                actions.append({"brand": "vesync", "id": vesync_id, "action": "off", "mode": None})
            elif "thấp" in text or "1" in text:
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "1"})
            elif "trung bình" in text or "2" in text:
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "2"})
            elif "cao" in text or "mạnh" in text or "3" in text:
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "3"})
            elif "tự động" in text or "auto" in text:
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "auto"})
            elif "ngủ" in text or "sleep" in text:
                actions.append({"brand": "vesync", "id": vesync_id, "action": "set_mode", "mode": "sleep"})
            elif "bật" in text or "mở" in text:
                actions.append({"brand": "vesync", "id": vesync_id, "action": "on", "mode": None})

    # 2. BẮT LỆNH MÁY CHO MÈO ĂN (Rojeco)
    if "mèo" in text or "ăn" in text or "hạt" in text:
        rojeco_id = next((d.id for d in devices_list if d.brand == "rojeco"), None)
        if rojeco_id:
            mode = "1" # Mặc định 1 phần
            if "2 phần" in text or "hai phần" in text: mode = "2"
            if "3 phần" in text or "ba phần" in text: mode = "3"
            actions.append({"brand": "rojeco", "id": rojeco_id, "action": "set_mode", "mode": mode})

    # 3. BẮT LỆNH CỬA CUỐN (Tuya)
    if "cửa" in text or "cuốn" in text:
        tuya_id = next((d.id for d in devices_list if d.brand == "tuya"), None)
        if tuya_id:
            if "mở" in text or "lên" in text:
                actions.append({"brand": "tuya", "id": tuya_id, "action": "set_mode", "mode": "open"})
            elif "đóng" in text or "xuống" in text:
                actions.append({"brand": "tuya", "id": tuya_id, "action": "set_mode", "mode": "close"})
            elif "dừng" in text or "stop" in text:
                actions.append({"brand": "tuya", "id": tuya_id, "action": "set_mode", "mode": "stop"})

    return actions