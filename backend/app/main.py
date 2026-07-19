# backend/app/main.py

import sys
import os
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Nạp biến môi trường từ backend/.env TRƯỚC khi import các connector
# (credential Tuya/VeSync/Rojeco đọc từ os.getenv lúc khởi tạo).
load_dotenv()

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

# Vòng lặp Hẹn giờ chạy nền
from app.services.scheduler import scheduler_loop, execute_schedule_action

# Tạm thời comment Automation Engine để tránh lỗi chưa hoàn thiện
# from app.services.automation_engine import automation_engine, AutomationRule

# Import Database
from app.core.database import SessionLocal, engine, Base, get_db
from app.models.device import DeviceModel
from app.models.schedule import ScheduleModel  # đăng ký bảng schedules với Base

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
# Lifespan: khởi động connector + vòng lặp Hẹn giờ (Scheduler)
# =========================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Bắt đầu khởi động các connector...")

    async def _init_connector(brand: str, factory):
        """Khởi tạo 1 connector an toàn: lỗi 1 hãng không làm sập cả app."""
        try:
            plugin = factory()
            ok = await plugin.connect()
            device_manager.register_connector(brand, plugin)
            if not ok:
                logger.warning(f"Connector {brand} kết nối KHÔNG thành công (sẽ thử lại khi có lệnh).")
        except Exception as e:
            logger.error(f"Lỗi khởi động connector {brand}: {e}")

    await _init_connector("tuya", TuyaConnector)
    await _init_connector("vesync", lambda: VeSyncConnector(
        email=os.getenv("VESYNC_EMAIL", ""),
        password=os.getenv("VESYNC_PASSWORD", ""),
    ))
    await _init_connector("rojeco", RojecoConnector)

    # --- Vòng lặp Hẹn giờ (server luôn thức nhờ UptimeRobot ping /health) ---
    scheduler_task = asyncio.create_task(scheduler_loop(invalidate_cache=_cache_invalidate))

    yield

    # Shutdown: dừng scheduler sạch sẽ
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    logger.info("Đã dừng scheduler & shutdown app.")

app = FastAPI(title="Smart Home System API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
async def delete_device(device_id: str, db: Session = Depends(get_db)):
    # Dùng Depends(get_db) để session luôn được đóng (kể cả khi lỗi) — tránh leak.
    try:
        device = db.query(DeviceModel).filter(DeviceModel.id == device_id).first()
        if device:
            db.delete(device)
            db.commit()
            logger.info(f"Đã xóa thiết bị {device_id}")
            return {"status": "success", "message": f"Đã xóa thiết bị {device_id}"}
        return {"status": "error", "message": "Không tìm thấy thiết bị để xóa."}
    except Exception as e:
        db.rollback()
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
async def get_device_status(brand: str, device_id: str, fresh: bool = False):
    try:
        # fresh=1: bỏ qua cache (client gọi ngay sau lệnh điều khiển để lấy
        # trạng thái mới nhất). Poll định kỳ vẫn dùng cache bình thường.
        if not fresh:
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
async def parse_voice_command(command: VoiceCommand, db: Session = Depends(get_db)):
    # Depends(get_db): session tự đóng kể cả khi query lỗi — tránh leak.
    devices = db.query(DeviceModel).all()

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
    async def execute_single_action(action):
        brand = action.get("brand")
        dev_id = action.get("id")
        act_type = action.get("action")
        mode = action.get("mode")

        # Format tên hiển thị
        device_obj = next((d for d in devices if d.id == dev_id), None)
        dev_name = device_obj.name if device_obj else dev_id

        # FIX: local_parser phát 'turn_on'/'turn_off', AI phát 'on'/'off' —
        # nhận cả hai để lệnh local "bật máy lọc" không rơi vào khoảng trống.
        is_on = act_type in ("on", "turn_on") or mode == "on"
        is_off = act_type in ("off", "turn_off") or mode == "off"

        action_ui = ""
        if is_on: action_ui = "Bật"
        elif is_off: action_ui = "Tắt"
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
                if is_off:
                    success = await connector.turn_off(dev_id)
                elif is_on:
                    success = await connector.turn_on(dev_id)
                elif mode and hasattr(connector, 'set_mode'):
                    success = await connector.set_mode(dev_id, mode)
            # FIX: invalidate cache như các endpoint control — để lần đọc
            # trạng thái kế tiếp không dính bản cache cũ (~3s).
            _cache_invalidate(brand, dev_id)
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
# API - Hẹn giờ (Schedules CRUD)
# =========================================================
import re as _re

class ScheduleCreate(BaseModel):
    name: str = ""
    brand: str
    device_id: str
    action_type: str                 # on | off | mode
    action_value: str | None = None  # bắt buộc khi action_type == mode
    time: str                        # "HH:MM" giờ Asia/Ho_Chi_Minh
    days: str = ""                   # CSV 0-6 (0=Thứ2); rỗng = mỗi ngày
    enabled: bool = True

class ScheduleUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    device_id: str | None = None
    action_type: str | None = None
    action_value: str | None = None
    time: str | None = None
    days: str | None = None
    enabled: bool | None = None

def _validate_schedule_fields(action_type: str | None, action_value: str | None,
                              time_str: str | None, days: str | None) -> str | None:
    """Trả về thông báo lỗi (tiếng Việt) hoặc None nếu hợp lệ."""
    if action_type is not None:
        if action_type not in ("on", "off", "mode"):
            return "action_type phải là on | off | mode"
        if action_type == "mode" and not action_value:
            return "action_value bắt buộc khi action_type = mode"
    if time_str is not None and not _re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", time_str):
        return "time phải có dạng HH:MM (00:00–23:59)"
    if days:
        parts = [p.strip() for p in days.split(",") if p.strip()]
        if any(not p.isdigit() or int(p) > 6 for p in parts):
            return "days phải là CSV các số 0-6 (0=Thứ2 … 6=CN)"
    return None

def _schedule_to_dict(s: ScheduleModel) -> dict:
    return {
        "id": s.id, "name": s.name, "brand": s.brand, "device_id": s.device_id,
        "action_type": s.action_type, "action_value": s.action_value,
        "time": s.time, "days": s.days or "", "enabled": bool(s.enabled),
        "last_fired_date": s.last_fired_date,
    }

@app.get("/api/schedules")
async def list_schedules(db: Session = Depends(get_db)):
    schedules = db.query(ScheduleModel).order_by(ScheduleModel.time).all()
    return {"status": "success", "data": [_schedule_to_dict(s) for s in schedules]}

@app.post("/api/schedules")
async def create_schedule(body: ScheduleCreate, db: Session = Depends(get_db)):
    err = _validate_schedule_fields(body.action_type, body.action_value, body.time, body.days)
    if err:
        return {"status": "error", "message": err}
    try:
        sch = ScheduleModel(
            name=body.name, brand=body.brand, device_id=body.device_id,
            action_type=body.action_type, action_value=body.action_value,
            time=body.time, days=body.days, enabled=body.enabled,
        )
        db.add(sch)
        db.commit()
        db.refresh(sch)
        logger.info(f"⏰ Đã tạo lịch #{sch.id}: {sch.brand}/{sch.device_id} {sch.action_type} lúc {sch.time}")
        return {"status": "success", "data": _schedule_to_dict(sch)}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi tạo lịch: {e}")
        return {"status": "error", "message": str(e)}

@app.patch("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, body: ScheduleUpdate, db: Session = Depends(get_db)):
    sch = db.query(ScheduleModel).filter(ScheduleModel.id == schedule_id).first()
    if not sch:
        return {"status": "error", "message": "Không tìm thấy lịch."}
    fields = body.model_dump(exclude_unset=True)
    err = _validate_schedule_fields(
        fields.get("action_type", sch.action_type),
        fields.get("action_value", sch.action_value),
        fields.get("time"), fields.get("days"),
    )
    if err:
        return {"status": "error", "message": err}
    try:
        for key, value in fields.items():
            setattr(sch, key, value)
        # Đổi giờ/bật lại lịch -> cho phép kích hoạt lại trong hôm nay nếu tới giờ mới.
        if "time" in fields or fields.get("enabled") is True:
            sch.last_fired_date = None
        db.commit()
        db.refresh(sch)
        return {"status": "success", "data": _schedule_to_dict(sch)}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi sửa lịch #{schedule_id}: {e}")
        return {"status": "error", "message": str(e)}

@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    sch = db.query(ScheduleModel).filter(ScheduleModel.id == schedule_id).first()
    if not sch:
        return {"status": "error", "message": "Không tìm thấy lịch."}
    try:
        db.delete(sch)
        db.commit()
        logger.info(f"⏰ Đã xóa lịch #{schedule_id}")
        return {"status": "success", "message": f"Đã xóa lịch #{schedule_id}"}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi xóa lịch #{schedule_id}: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/schedules/{schedule_id}/run")
async def run_schedule_now(schedule_id: int, db: Session = Depends(get_db)):
    """Chạy NGAY hành động của lịch (để test), không ảnh hưởng last_fired_date."""
    sch = db.query(ScheduleModel).filter(ScheduleModel.id == schedule_id).first()
    if not sch:
        return {"status": "error", "message": "Không tìm thấy lịch."}
    try:
        ok = await execute_schedule_action(
            sch.brand, sch.device_id, sch.action_type, sch.action_value,
            invalidate_cache=_cache_invalidate,
        )
        if not ok:
            return {"status": "error", "message": "Thiết bị không nhận lệnh."}
        return {"status": "success", "message": f"Đã chạy lịch #{schedule_id}"}
    except Exception as e:
        logger.error(f"Lỗi chạy lịch #{schedule_id}: {e}")
        return {"status": "error", "message": str(e)}

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