# backend/app/main.py

import sys
import os
import asyncio
import logging
from datetime import datetime

from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, Depends
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session

# Import các Connector và Manager
from app.services.local_parser import parse_command_locally
from app.services.connector_manager import device_manager
from app.services.tuya_connector import TuyaConnector
from app.services.vesync_connector import VeSyncConnector
from app.services.rojeco_connector import RojecoConnector

# Import AI Parser (Đã đổi thành AI dùng cho OpenRouter)
from app.services.ai_parser import parse_command_with_ai

# Tạm thời comment Automation Engine để tránh lỗi chưa hoàn thiện
# from app.services.automation_engine import automation_engine, AutomationRule

# Import Database
from app.core.database import SessionLocal, engine, Base, get_db
from app.models.device import DeviceModel

# =========================================================
# CẤU HÌNH HỆ THỐNG GHI LOG CHUYÊN NGHIỆP
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SmartHome.Main")

# =========================================================
# FIX UTF-8 tiếng Việt trên Windows terminal
# =========================================================
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# =========================================================
# Tạo Database
# =========================================================
logger.info("Đang khởi tạo Database...")
Base.metadata.create_all(bind=engine)

# =========================================================
# FastAPI App
# =========================================================
app = FastAPI(title="Smart Home System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# Startup Event
# =========================================================
@app.on_event("startup")
async def startup_event():
    logger.info("Bắt đầu khởi động các connector...")

    # --- Tuya ---
    tuya_plugin = TuyaConnector()
    await tuya_plugin.connect()
    device_manager.register_connector("tuya", tuya_plugin)

    # --- VeSync ---
    vesync_plugin = VeSyncConnector(
        email="haphivuboris@gmail.com",
        password="Hoalong741369@"
    )
    await vesync_plugin.connect()
    device_manager.register_connector("vesync", vesync_plugin)

    # --- Rojeco ---
    rojeco_plugin = RojecoConnector()
    await rojeco_plugin.connect()
    device_manager.register_connector("rojeco", rojeco_plugin)

    # =====================================================
    # Automation Rules (Đã đóng gói an toàn để phát triển sau)
    # =====================================================
    """
    def is_second_0(): return datetime.now().second == 0
    async def auto_turn_on():
        connector = device_manager.get_connector("tuya")
        await connector.turn_on("den_phong_khach")
    # rule1 = AutomationRule(name="Bật đèn", condition=is_second_0, action=auto_turn_on)
    # automation_engine.add_rule(rule1)
    # asyncio.create_task(automation_engine.start_engine())
    """

# =========================================================
# API - Get Devices
# =========================================================
@app.get("/api/devices")
async def get_all_devices(db: Session = Depends(get_db)):
    devices = db.query(DeviceModel).all()
    return {"status": "success", "data": devices}

# =========================================================
# API - Add & Delete Device
# =========================================================
@app.post("/api/devices")
async def add_device(id: str, name: str, brand: str, db: Session = Depends(get_db)):
    try:
        new_device = DeviceModel(id=id, name=name, brand=brand, is_active=True)
        db.add(new_device)
        db.commit()
        db.refresh(new_device)
        logger.info(f"Đã thêm thiết bị mới: {name} ({brand})")
        return {"status": "success", "message": f"Đã thêm: {name}"}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi thêm thiết bị: {e}")
        return {"status": "error", "message": f"Lỗi: {str(e)}"}

@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: str):
    try:
        db = SessionLocal()
        device = db.query(DeviceModel).filter(DeviceModel.id == device_id).first()
        if device:
            db.delete(device)
            db.commit()
            db.close()
            logger.info(f"Đã xóa thiết bị {device_id}")
            return {"status": "success", "message": f"Đã xóa thiết bị {device_id}"}
        db.close()
        return {"status": "error", "message": "Không tìm thấy thiết bị để xóa."}
    except Exception as e:
        logger.error(f"Lỗi xóa thiết bị: {e}")
        return {"status": "error", "message": str(e)}

# =========================================================
# API - Test Control Device (Action & Mode)
# =========================================================
@app.get("/api/test-control/{brand}/{device_id}")
async def test_control(brand: str, device_id: str, action: str = "on"):
    try:
        connector = device_manager.get_connector(brand)
        if action == "on":
            await connector.turn_on(device_id)
        else:
            await connector.turn_off(device_id)
        logger.info(f"Đã thực hiện lệnh {action} cho thiết bị {device_id} qua {brand}")
        return {"status": "success", "message": f"Đã {action} thiết bị {device_id} ({brand})"}
    except Exception as e:
        logger.error(f"Lỗi điều khiển {brand}: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/test-control/{brand}/{device_id}/mode")
async def test_control_mode(brand: str, device_id: str, mode: str):
    try:
        connector = device_manager.get_connector(brand)
        if hasattr(connector, 'set_mode'):
            await connector.set_mode(device_id, mode)
            logger.info(f"Đã chuyển chế độ {mode} cho thiết bị {device_id} qua {brand}")
            return {"status": "success", "message": f"Đã chuyển sang chế độ {mode}"}
        else:
            return {"status": "error", "message": "Thiết bị không hỗ trợ đổi chế độ"}
    except Exception as e:
        logger.error(f"Lỗi đổi chế độ {brand}: {e}")
        return {"status": "error", "message": str(e)}

# =========================================================
# API - Nhận Lệnh Giọng Nói (AI OpenRouter)
# =========================================================
class VoiceCommand(BaseModel):
    text: str

@app.post("/api/ai/parse")
async def parse_voice_command(command: VoiceCommand):
    db = SessionLocal()
    devices = db.query(DeviceModel).all()
    db.close()
    
    text_lower = command.text.lower()
    logger.info(f"Nhận lệnh giọng nói: '{command.text}'")
    actions = []
    
    # ---------------------------------------------------------
    # BỨC TƯỜNG LỬA: KIỂM TRA TỪ KHÓA THIẾT BỊ
    # ---------------------------------------------------------
    # Danh sách các từ khóa liên quan đến thiết bị trong nhà
    device_keywords = ["quạt", "lọc", "không khí", "mèo", "ăn", "hạt", "cửa", "cuốn", "đèn", "tất cả"]
    
    # Nếu câu nói KHÔNG chứa bất kỳ từ khóa nào ở trên -> Chặn luôn
    if not any(kw in text_lower for kw in device_keywords):
        logger.info("❌ Câu lệnh không chứa thiết bị. Bỏ qua AI.")
        return {"status": "success", "ai_understood": [], "execution_results": []}
    
    # KIỂM TRA CÂU PHỨC
    complex_keywords = [" và ", " rồi ", " với ", " nhưng "]
    is_complex_sentence = any(kw in text_lower for kw in complex_keywords)

    if not is_complex_sentence:
        actions = parse_command_locally(text_lower, devices)
    
    if actions:
        logger.info(f"⚡ Local Parser đã hiểu lệnh: {actions}")
    else:
        logger.info("🤖 Chuyển cho AI phân tích câu nói...")
        actions = await parse_command_with_ai(command.text, devices)

    # 3. Thực thi lệnh
    results = []
    for action in actions:
        brand = action.get("brand")
        dev_id = action.get("id")
        act_type = action.get("action")
        mode = action.get("mode")
        
        # Lấy Tên thiết bị để hiển thị lên Chat đẹp hơn
        device_obj = next((d for d in devices if d.id == dev_id), None)
        dev_name = device_obj.name if device_obj else dev_id
        
        # Dịch Action sang Tiếng Việt cho người dùng dễ hiểu
        action_ui = ""
        if act_type == "on" or mode == "on": action_ui = "Bật"
        elif act_type == "off" or mode == "off": action_ui = "Tắt"
        elif mode:
            if mode == "open": action_ui = "Mở cửa"
            elif mode == "close": action_ui = "Đóng cửa"
            elif mode == "stop": action_ui = "Dừng"
            else: action_ui = f"Chế độ {mode}"
        else: action_ui = "Thực thi"

        success = False
        try:
            connector = device_manager.get_connector(brand)
            if connector:
                # Sửa lỗi tắt máy lọc: Tối ưu lại cấu trúc If/Else
                if act_type == "off" or mode == "off":
                    success = await connector.turn_off(dev_id)
                elif act_type == "on" or mode == "on":
                    success = await connector.turn_on(dev_id)
                elif mode and hasattr(connector, 'set_mode'):
                    success = await connector.set_mode(dev_id, mode)
        except Exception as e:
            logger.error(f"[AI Execution Error] {e}")

        # Gửi Tên và Action tiếng Việt về cho App
        results.append({
            "device_name": dev_name, 
            "action": action_ui, 
            "success": success
        })

    return {"status": "success", "ai_understood": actions, "execution_results": results}

# =========================================================
# WebSocket (Giữ kết nối cho App)
# =========================================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client WebSocket mới đã kết nối.")
    try:
        while True:
            user_text = await websocket.receive_text()
            await websocket.send_text("📡 Server đã nhận lệnh, đang xử lý qua AI...")
    except Exception as e:
        logger.warning(f"WebSocket ngắt kết nối: {e}")

# =========================================================
# Root & Favicon
# =========================================================
@app.get("/")
async def root(): 
    return {"message": "Hệ thống Smart Home Backend đang hoạt động!"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon(): 
    return Response(content="", media_type="image/x-icon")