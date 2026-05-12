def parse_command_locally(text: str, devices_list: list) -> list:
    """
    Hệ thống phân tích lệnh nội bộ siêu tốc.
    Bao quát các từ đồng nghĩa, từ lóng tiếng Việt.
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