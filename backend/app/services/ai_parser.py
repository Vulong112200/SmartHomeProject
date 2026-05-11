import google.generativeai as genai
import json

# Điền API Key của bạn vào đây
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
genai.configure(api_key=GEMINI_API_KEY)

# Sử dụng model Gemini 1.5 Flash (Xử lý cực nhanh cho lệnh giọng nói)
model = genai.GenerativeModel('gemini-1.5-flash')

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