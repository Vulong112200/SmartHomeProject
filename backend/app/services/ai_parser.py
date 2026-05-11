import google.generativeai as genai
import json
import os
from dotenv import load_dotenv

# Tự động tìm file .env (nếu có ở local)
load_dotenv()

# Lấy Key từ Environment của Render hoặc file .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("[AI Error] ⚠️ Không tìm thấy GEMINI_API_KEY! Hãy kiểm tra lại Settings trên Render.")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    
models = genai.list_models() 
for model in models: 
    print("MODEL:", model.name) 
    if hasattr(model, "supported_generation_methods"): 
        print("METHODS:", model.supported_generation_methods) 
        print("-" * 50)

model = genai.GenerativeModel('gemini-1.5-flash-latest')

async def parse_command_with_gemini(command_text: str, devices_list: list) -> list:
    """
    Hàm này gửi câu nói của người dùng và danh sách thiết bị cho Gemini,
    ép Gemini trả về danh sách các hành động (JSON).
    """
    
    # 1. Gom thông tin thiết bị đang có trong nhà bạn để đưa cho AI
    device_context = []
    for dev in devices_list:
        device_context.append(f"- ID: {dev.id}, Tên: {dev.name}, Hãng: {dev.brand}")
    
    devices_str = "\n".join(device_context)

    # 2. VIẾT PROMPT "THIẾT QUÂN LUẬT"
    prompt = f"""
    Bạn là hệ thống điều khiển nhà thông minh.
    Dưới đây là danh sách thiết bị đang có trong nhà:
    {devices_str}
    
    Lệnh của người dùng: "{command_text}"
    
    Nhiệm vụ: Phân tích lệnh và trả về DUY NHẤT một mảng JSON (không giải thích, không thêm định dạng markdown).
    Cấu trúc của mỗi phần tử trong mảng JSON phải là:
    {{
        "brand": "tên hãng (ví dụ: rojeco, tuya, vesync)",
        "id": "ID của thiết bị",
        "action": "turn_on, turn_off, hoặc set_mode",
        "mode": "giá trị truyền vào (nếu là rojeco thì là số lượng phần ví dụ '1', nếu là tuya thì 'open', 'close', 'stop')"
    }}
    
    Nếu câu nói không liên quan đến điều khiển thiết bị, trả về mảng rỗng: []
    """

    try:
        # 3. Gửi lệnh cho Gemini
        response = model.generate_content(
            prompt,
            # ÉP KIỂU TRẢ VỀ LÀ JSON ĐỂ AI KHÔNG NÓI NHẢM
            generation_config={"response_mime_type": "application/json"}
        )
        
        # 4. Đọc kết quả từ AI
        actions = json.loads(response.text)
        print(f"[Gemini Output]: {actions}")
        return actions
        
    except Exception as e:
        print(f"[Gemini Error]: Lỗi xử lý AI - {e}")
        return [] # Nếu lỗi thì không làm gì cả để đảm bảo an toàn