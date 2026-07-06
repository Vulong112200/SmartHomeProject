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

import time
from fastapi import Request

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
# CACHE TRẠNG THÁI NGẮN HẠN
# Poll định kỳ từ nhiều card có thể gọi status liên tục -> cache ~3s để
# giảm số lần gọi cloud (Tuya/VeSync), tăng tốc phản hồi. Bị xóa ngay sau
# mỗi lệnh điều khiển để lần đọc kế tiếp lấy trạng thái mới.
# =========================================================
_STATUS_CACHE_TTL = 3.0  # giây
_status_cache: dict = {}  # {(brand, device_id): (monotonic_ts, data)}

def _cache_get(brand: str, device_id: str):
    entry = _status_cache.get((brand, device_id))
    if entry and (time.monotonic() - entry[0]) < _STATUS_CACHE_TTL:
        return entry[1]
    return None

def _cache_set(brand: str, device_id: str, data):
    _status_cache[(brand, device_id)] = (time.monotonic(), data)

def _cache_invalidate(brand: str, device_id: str):
    _status_cache.pop((brand, device_id), None)

# =========================================================
# API - Test Control Device (Action & Mode)
# =========================================================
@app.get("/api/test-control/{brand}/{device_id}")
async def test_control(brand: str, device_id: str, action: str = "on"):
    try:
        connector = device_manager.get_connector(brand)
        if action == "on":
            ok = await connector.turn_on(device_id)
        else:
            ok = await connector.turn_off(device_id)
        _cache_invalidate(brand, device_id)
        if not ok:
            logger.warning(f"Lệnh {action} cho {device_id} qua {brand} không thành công")
            return {"status": "error", "message": f"Thiết bị {device_id} không nhận lệnh {action}"}
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
            ok = await connector.set_mode(device_id, mode)
            _cache_invalidate(brand, device_id)
            if not ok:
                logger.warning(f"Đổi chế độ {mode} cho {device_id} qua {brand} không thành công")
                return {"status": "error", "message": f"Thiết bị không nhận chế độ {mode}"}
            logger.info(f"Đã chuyển chế độ {mode} cho thiết bị {device_id} qua {brand}")
            return {"status": "success", "message": f"Đã chuyển sang chế độ {mode}"}
        else:
            return {"status": "error", "message": "Thiết bị không hỗ trợ đổi chế độ"}
    except Exception as e:
        logger.error(f"Lỗi đổi chế độ {brand}: {e}")
        return {"status": "error", "message": str(e)}

# =========================================================
# API - Lấy trạng thái THẬT của thiết bị (query từ phần cứng)
# =========================================================
@app.get("/api/devices/{brand}/{device_id}/status")
async def get_device_status(brand: str, device_id: str):
    try:
        cached = _cache_get(brand, device_id)
        if cached is not None:
            return {"status": "success", "data": cached, "cached": True}
        connector = device_manager.get_connector(brand)
        if not connector:
            return {"status": "error", "message": f"Không tìm thấy connector cho {brand}"}
        state = await connector.get_device_state(device_id)
        _cache_set(brand, device_id, state)
        return {"status": "success", "data": state}
    except Exception as e:
        logger.error(f"Lỗi lấy trạng thái {brand}/{device_id}: {e}")
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
    # results = []
    # for action in actions:
    #     brand = action.get("brand")
    #     dev_id = action.get("id")
    #     act_type = action.get("action")
    #     mode = action.get("mode")
        
    #     # Lấy Tên thiết bị để hiển thị lên Chat đẹp hơn
    #     device_obj = next((d for d in devices if d.id == dev_id), None)
    #     dev_name = device_obj.name if device_obj else dev_id
        
    #     # Dịch Action sang Tiếng Việt cho người dùng dễ hiểu
    #     action_ui = ""
    #     if act_type == "on" or mode == "on": action_ui = "Bật"
    #     elif act_type == "off" or mode == "off": action_ui = "Tắt"
    #     elif mode:
    #         if mode == "open": action_ui = "Mở cửa"
    #         elif mode == "close": action_ui = "Đóng cửa"
    #         elif mode == "stop": action_ui = "Dừng"
    #         else: action_ui = f"Chế độ {mode}"
    #     else: action_ui = "Thực thi"

    #     success = False
    #     try:
    #         connector = device_manager.get_connector(brand)
    #         if connector:
    #             # Sửa lỗi tắt máy lọc: Tối ưu lại cấu trúc If/Else
    #             if act_type == "off" or mode == "off":
    #                 success = await connector.turn_off(dev_id)
    #             elif act_type == "on" or mode == "on":
    #                 success = await connector.turn_on(dev_id)
    #             elif mode and hasattr(connector, 'set_mode'):
    #                 success = await connector.set_mode(dev_id, mode)
    #     except Exception as e:
    #         logger.error(f"[AI Execution Error] {e}")

    #     # Gửi Tên và Action tiếng Việt về cho App
    #     results.append({
    #         "device_name": dev_name, 
    #         "action": action_ui, 
    #         "success": success
    #     })

    # return {"status": "success", "ai_understood": actions, "execution_results": results}
    
    async def execute_single_action(action):
        brand = action.get("brand")
        dev_id = action.get("id")
        act_type = action.get("action")
        mode = action.get("mode")
        
        # Format tên hiển thị
        device_obj = next((d for d in devices if d.id == dev_id), None)
        dev_name = device_obj.name if device_obj else dev_id
        
        action_ui = ""
        if act_type == "on" or mode == "on": action_ui = "Bật"
        elif act_type == "off" or mode == "off": action_ui = "Tắt"
        elif mode:
            if mode == "open": action_ui = "Mở"
            elif mode == "close": action_ui = "Đóng"
            elif mode == "stop": action_ui = "Dừng"
            else: action_ui = f"Chế độ {mode}"
        else: action_ui = "Thực thi"

        success = False
        try:
            connector = device_manager.get_connector(brand)
            if connector:
                if act_type == "off" or mode == "off":
                    success = await connector.turn_off(dev_id)
                elif act_type == "on" or mode == "on":
                    success = await connector.turn_on(dev_id)
                elif mode and hasattr(connector, 'set_mode'):
                    success = await connector.set_mode(dev_id, mode)
        except Exception as e:
            logger.error(f"[AI Execution Error] {e}")

        return {
            "device_name": dev_name, 
            "action": action_ui, 
            "success": success
        }

    # Bắn TẤT CẢ các lệnh IoT cùng một lúc (Tốc độ x2, x3)
    # Nếu câu nói có 3 thiết bị, nó sẽ chạy song song cả 3.
    tasks = [execute_single_action(action) for action in actions]
    results = await asyncio.gather(*tasks)

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
@app.api_route("/", methods=["GET", "HEAD"])
async def root(): 
    """
    Xử lý yêu cầu từ trình duyệt (GET) và UptimeRobot (HEAD).
    Việc hỗ trợ HEAD giúp giảm băng thông và tăng tốc độ phản hồi.
    """
    return {"message": "Hệ thống Smart Home Backend đang hoạt động!"}

@app.api_route("/health", methods=["GET", "HEAD"]) 
async def health_check():
    """
    Endpoint chuyên biệt cho việc kiểm tra trạng thái hệ thống.
    """
    return {"status": "online"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon(): 
    return Response(content="", media_type="image/x-icon")

# ==========================================
# MIDDLEWARE ĐO THỜI GIAN PHẢN HỒI
# ==========================================
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    # Ghi lại thời gian bắt đầu nhận request
    start_time = time.time()
    
    # Tiếp tục xử lý các logic của API
    response = await call_next(request)
    
    # Tính toán tổng thời gian xử lý (giây)
    process_time = time.time() - start_time
    
    # Thêm thông tin thời gian xử lý vào Header của phản hồi
    response.headers["X-Process-Time"] = str(process_time)
    
    # In ra log để bạn theo dõi trực tiếp trên Render Logs
    print(f"Path: {request.url.path} | Time: {process_time:.4f}s")
    
    return response