# backend/app/services/ai_parser.py
from typing import Dict, Any

class AICommandParser:
    """
    Lớp xử lý Ngôn ngữ Tự nhiên (NLP).
    Nhiệm vụ: Chuyển đổi câu lệnh tự do của người dùng thành cấu trúc JSON chuẩn mực.
    """
    def parse_command(self, text: str) -> Dict[str, Any]:
        # Chuẩn hóa chuỗi đầu vào thành chữ thường để dễ xử lý
        text = text.lower()
        
        # Giá trị mặc định
        intent = "unknown"
        device_id = "unknown"
        brand = "tuya"  # Hãng mặc định

        # 1. Trích xuất Ý định (Intent Extraction)
        if "bật" in text or "mở" in text:
            intent = "on"
        elif "tắt" in text or "đóng" in text:
            intent = "off"

        # 2. Trích xuất Thiết bị (Entity Extraction)
        if "đèn" in text:
            device_id = "den_phong_khach"
            brand = "tuya"
        elif "quạt" in text:
            device_id = "quat_phong_ngu"
            brand = "vesync" # Giả lập hệ sinh thái VeSync
        elif "máy cho ăn" in text or "kato" in text:
            device_id = "rojeco_feeder"
            brand = "rojeco"

        return {
            "intent": intent,
            "device_id": device_id,
            "brand": brand,
            "original_text": text
        }

# Khởi tạo một đối tượng duy nhất (Singleton)
ai_parser = AICommandParser()