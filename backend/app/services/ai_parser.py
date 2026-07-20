import os
import json
import logging
from openai import AsyncOpenAI
from dotenv import load_dotenv

# ==========================================
# CẤU HÌNH LOGGER CHO AI
# ==========================================
logger = logging.getLogger("SmartHome.AI")

# Tự động tìm file .env (nếu có ở local)
load_dotenv()

# Lấy Key từ Environment của Render
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    logger.error("⚠️ Không tìm thấy OPENROUTER_API_KEY! Hãy kiểm tra lại biến môi trường trên Render.")

# Khởi tạo client trỏ thẳng vào server của OpenRouter.
# LƯU Ý: khởi tạo LƯỜI (lazy) — nếu thiếu key, app vẫn boot bình thường
# (local parser vẫn chạy), chỉ phần AI fallback bị vô hiệu.
_client: AsyncOpenAI | None = None

def _get_client() -> AsyncOpenAI | None:
    global _client
    if _client is None and OPENROUTER_API_KEY:
        _client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
    return _client

async def parse_command_with_ai(command_text: str, devices_list: list) -> list:
    """
    Hàm này gửi câu nói của người dùng và danh sách thiết bị cho OpenRouter (Model Free),
    ép AI trả về danh sách các hành động (JSON).
    """
    
    # 1. Gom thông tin thiết bị đang có trong nhà bạn để đưa cho AI
    device_context = []
    for dev in devices_list:
        device_context.append(f"- ID: {dev.id}, Tên: {dev.name}, Hãng: {dev.brand}")
    
    devices_str = "\n".join(device_context)

    # 2. PROMPT THIẾT QUÂN LUẬT
    prompt = f"""
    Bạn là hệ thống phân tích lệnh cho nhà thông minh.
    Danh sách thiết bị:
    {devices_str}
    
    Quy tắc TỐI THƯỢNG:
    1. CHỈ điều khiển thiết bị được người dùng nhắc đến đích danh.
    2. NẾU câu nói không có nghĩa, hoặc KHÔNG nhắc đến bất kỳ thiết bị nào (ví dụ: 'bận nó không thấy mất tự động', 'hôm nay trời đẹp', v.v.), BẮT BUỘC trả về mảng rỗng: []
    3. Trả về DUY NHẤT JSON.
    4. NẾU câu có GIỜ HẸN (hẹn, lúc X giờ, X giờ sáng/chiều/tối, ngày mai, từ X đến Y...):
       KHÔNG thi hành ngay mà trả về intent "schedule" với các trường:
       "time"/"end_time" dạng "HH:MM" 24 giờ; "day_offset": 0 (hôm nay) hoặc 1 (ngày mai);
       "recurring_daily": true nếu nói "mỗi ngày/hàng ngày"; nếu là KHOẢNG (từ X đến Y)
       mà người dùng không nói hành động kết thúc thì "end_action": "turn_off".

    Ví dụ:
    - "Bật máy lọc": [{{ "brand": "vesync", "id": "<id>", "action": "on", "mode": None }}]
    - "Đóng cửa": [{{ "brand": "tuya", "id": "<id>", "action": "set_mode", "mode": "close" }}]
    - "Cho mèo ăn": [{{ "brand": "rojeco", "id": "<id>", "action": "set_mode", "mode": "1" }}]
    - "Hẹn 16 giờ 30 bật quạt mức cao": [{{ "intent": "schedule", "brand": "vesync", "id": "<id>", "action": "set_mode", "mode": "3", "time": "16:30", "end_time": null, "end_action": null, "end_mode": null, "day_offset": 0, "recurring_daily": false }}]
    - "6 giờ sáng mai mở cửa": [{{ "intent": "schedule", "brand": "tuya", "id": "<id>", "action": "set_mode", "mode": "open", "time": "06:00", "end_time": null, "end_action": null, "end_mode": null, "day_offset": 1, "recurring_daily": false }}]
    - "Từ 16 giờ 30 đến 17 giờ 30 bật quạt mức cao": [{{ "intent": "schedule", "brand": "vesync", "id": "<id>", "action": "set_mode", "mode": "3", "time": "16:30", "end_time": "17:30", "end_action": "turn_off", "end_mode": null, "day_offset": 0, "recurring_daily": false }}]
    - "Làm bậy bạ đi": []

    Lệnh hiện tại: "{command_text}"
    Trả về JSON:
    """

    client = _get_client()
    if client is None:
        logger.warning("Bỏ qua AI parse vì thiếu OPENROUTER_API_KEY.")
        return []

    try:
        # 3. GỌI MODEL MIỄN PHÍ TỪ OPENROUTER
        # Hậu tố :free đảm bảo không bao giờ tính tiền.
        # Có thể thử "meta-llama/llama-3.3-70b-instruct:free" nếu muốn.
        response = await client.chat.completions.create(
            # model=" google/gemini-2.5-flash:free",
            model="openrouter/free",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
            
        )
        
        # 4. LẤY KẾT QUẢ VÀ LÀM SẠCH JSON
        result_text = (response.choices[0].message.content or "").strip()
        
        # Dọn dẹp rác markdown (```json ... ```) nếu AI lỡ thêm vào
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        elif result_text.startswith("```"):
            result_text = result_text[3:]
            
        if result_text.endswith("```"):
            result_text = result_text[:-3]
            
        try:
            # Nếu OpenRouter trả về rỗng, trả về mảng rỗng
            if not result_text:
                return []
                
            actions = json.loads(result_text.strip())
            logger.info(f"Phân tích thành công: {actions}")
            return actions
        except json.JSONDecodeError as e:
            logger.error(f"❌ AI trả về định dạng JSON sai: {result_text}")
            return [] # Trả về mảng rỗng thay vì làm sập server
        
    except Exception as e:
        # exc_info=True sẽ in ra chi tiết lỗi để dễ debug
        logger.error(f"Lỗi khi gọi OpenRouter API: {e}", exc_info=True)
        return []