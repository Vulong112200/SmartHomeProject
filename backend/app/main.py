# backend/app/main.py
import sys
import os
import asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from app.services.connector_manager import device_manager
from app.services.tuya_connector import TuyaConnector
from app.services.ai_parser import ai_parser
from app.services.automation_engine import automation_engine, AutomationRule

from app.core.database import engine, Base
from app.models.device import DeviceModel

from sqlalchemy.orm import Session
from fastapi import Depends
from app.core.database import get_db

from app.services.vesync_connector import VeSyncConnector
from app.services.rojeco_connector import RojecoConnector

# Ép hệ thống Windows sử dụng UTF-8 để in log ra Terminal không bị lỗi font
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Tạo toàn bộ các bảng trong Database dựa trên Models đã định nghĩa
print("Đang khởi tạo Database...")
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Smart Home System API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Cho phép mọi nguồn truy cập
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- KHỞI TẠO HỆ THỐNG KHI SERVER CHẠY ---
@app.on_event("startup")
async def startup_event():
    print("Khởi động hệ thống Connector...")
    tuya_plugin = TuyaConnector(api_key="tuya_key_123", api_secret="tuya_secret_456")
    await tuya_plugin.connect()
    device_manager.register_connector("tuya", tuya_plugin)

    # --- KHỞI TẠO VESYNC (THẬT) ---
    # BẠN HÃY THAY EMAIL VÀ MẬT KHẨU APP VESYNC CỦA BẠN VÀO ĐÂY:
    vesync_plugin = VeSyncConnector(email="haphivuboris@gmail.com", password="Hoalong741369@")
    await vesync_plugin.connect()
    device_manager.register_connector("vesync", vesync_plugin)
    
    rojeco_plugin = RojecoConnector()
    await rojeco_plugin.connect()
    device_manager.register_connector("rojeco", rojeco_plugin)

    # --- THÊM LOGIC TỰ ĐỘNG HÓA VÀO ĐÂY ---
    # 1. Định nghĩa điều kiện (IF)
    def is_second_0():
        return datetime.now().second == 0
        
    def is_second_30():
        return datetime.now().second == 30

    # 2. Định nghĩa hành động (THEN)
    async def auto_turn_on():
        connector = device_manager.get_connector("tuya")
        await connector.turn_on("den_phong_khach")
        
    async def auto_turn_off():
        connector = device_manager.get_connector("tuya")
        await connector.turn_off("den_phong_khach")

    # 3. Tạo và đăng ký kịch bản
    rule1 = AutomationRule(name="Bật đèn vào đầu phút", condition=is_second_0, action=auto_turn_on)
    rule2 = AutomationRule(name="Tắt đèn vào giữa phút", condition=is_second_30, action=auto_turn_off)
    
    automation_engine.add_rule(rule1)
    automation_engine.add_rule(rule2)

    # 4. KHỞI CHẠY ENGINE CHẠY NGẦM BẰNG ASYNCIO TASK
    asyncio.create_task(automation_engine.start_engine())

@app.get("/api/devices")
async def get_all_devices(db: Session = Depends(get_db)):
    """Lấy danh sách toàn bộ thiết bị đang lưu trong Database"""
    # Lệnh db.query sẽ tự động dịch thành câu lệnh SQL: SELECT * FROM devices;
    devices = db.query(DeviceModel).all()
    return {"status": "success", "data": devices}

@app.post("/api/devices")
async def add_device(id: str, name: str, brand: str, db: Session = Depends(get_db)):
    """Thêm một thiết bị mới vào Database từ App điện thoại"""
    try:
        # Tạo một bản ghi mới
        new_device = DeviceModel(id=id, name=name, brand=brand, is_active=True)
        # Lưu vào DB
        db.add(new_device)
        db.commit() # Xác nhận lưu
        db.refresh(new_device)
        return {"status": "success", "message": f"Đã thêm thiết bị: {name}"}
    except Exception as e:
        db.rollback() # Nếu lỗi thì hoàn tác
        return {"status": "error", "message": f"Không thể thêm thiết bị: {str(e)}"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content="", media_type="image/x-icon")

@app.get("/")
async def root():
    return {"message": "Hệ thống Smart Home Backend đang hoạt động!"}

# --- API KIỂM TRA ĐIỀU KHIỂN THIẾT BỊ ---
@app.get("/api/test-control/{brand}/{device_id}")
async def test_control(brand: str, device_id: str, action: str = "on"):
    try:
        # Bước 1: Tìm đúng Plugin của hãng (ví dụ: brand = "tuya")
        connector = device_manager.get_connector(brand)
        
        # Bước 2: Ra lệnh
        if action == "on":
            await connector.turn_on(device_id)
        else:
            await connector.turn_off(device_id)
            
        return {"status": "success", "message": f"Đã thực hiện lệnh {action} cho thiết bị {device_id} qua {brand}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
        
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Nhận câu lệnh bằng chữ từ app điện thoại
            user_text = await websocket.receive_text()
            
            # 1. AI Phân tích câu nói
            parsed_cmd = ai_parser.parse_command(user_text)
            
            # 2. Đưa ra hành động
            if parsed_cmd["intent"] in ["on", "off"] and parsed_cmd["device_id"] != "unknown":
                try:
                    # Tìm đúng Plugin của hãng
                    connector = device_manager.get_connector(parsed_cmd["brand"])
                    
                    # Ra lệnh
                    if parsed_cmd["intent"] == "on":
                        await connector.turn_on(parsed_cmd["device_id"])
                    else:
                        await connector.turn_off(parsed_cmd["device_id"])
                        
                    # Phản hồi thành công về app
                    response = f"🤖 AI: Đã {parsed_cmd['intent'].upper()} thiết bị {parsed_cmd['device_id']} ({parsed_cmd['brand']})"
                except ValueError:
                    response = f"🤖 AI: Chưa cấu hình hệ sinh thái {parsed_cmd['brand']}"
                except Exception as e:
                    response = f"❌ Lỗi: {str(e)}"
            else:
                response = f"🤖 AI: Tôi chưa hiểu lệnh '{user_text}'. Bạn thử nói 'Bật đèn' hoặc 'Tắt quạt' xem?"
            
            # 3. Gửi kết quả ngược lại cho người dùng
            await websocket.send_text(response)
    except Exception as e:
        print(f"Kết nối bị ngắt: {e}")