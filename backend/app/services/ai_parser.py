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

# Khởi tạo client trỏ thẳng vào server của OpenRouter
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

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
    Bạn là hệ thống điều khiển nhà thông minh.
    Danh sách thiết bị hiện có:
    {devices_str}
    
    Lệnh của người dùng: "{command_text}"
    
    Nhiệm vụ: Phân tích lệnh và trả về DUY NHẤT một mảng JSON (không giải thích, không trò chuyện).
    Cấu trúc của mỗi phần tử:
    {{
        "brand": "tên hãng (ví dụ: rojeco, tuya, vesync)",
        "id": "ID thiết bị",
        "action": "turn_on, turn_off, hoặc set_mode",
        "mode": "giá trị (ví dụ '1', '2' đối với rojeco/vesync, hoặc 'open', 'close', 'stop' đối với tuya)"
    }}
    
    LƯU Ý CỰC KỲ QUAN TRỌNG: 
    - CHỈ trả về thiết bị được người dùng nhắc đến một cách rõ ràng. 
    - TUYỆT ĐỐI KHÔNG tự ý thêm các thiết bị khác vào JSON. 
    - Quạt lọc/máy lọc thì ID là vsaq325492d4dce9e0f8eb348bb3be41. Trung bình = mode '2'.
    - Nếu câu nói không khớp với thiết bị nào, trả về []
    """

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
        result_text = response.choices[0].message.content.strip()
        
        # Dọn dẹp rác markdown (```json ... ```) nếu AI lỡ thêm vào
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        elif result_text.startswith("```"):
            result_text = result_text[3:]
            
        if result_text.endswith("```"):
            result_text = result_text[:-3]
            
        # 5. CHUYỂN ĐỔI SANG MẢNG PYTHON
        actions = json.loads(result_text.strip())
        logger.info(f"Phân tích thành công: {actions}")
        return actions
        
    except Exception as e:
        # exc_info=True sẽ in ra chi tiết lỗi để dễ debug
        logger.error(f"Lỗi khi gọi OpenRouter API: {e}", exc_info=True)
        return []