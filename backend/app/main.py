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
from fastapi import FastAPI, WebSocket, Depends, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session

# Import các Connector và Manager
from app.services.local_parser import parse_command_locally
from app.services.connector_manager import device_manager
from app.services.tuya_connector import TuyaConnector
from app.services.rojeco_connector import RojecoConnector
from app.services import connector_factory

# Import AI Parser (Đã đổi thành AI dùng cho OpenRouter)
from app.services.ai_parser import parse_command_with_ai

# Vòng lặp Hẹn giờ chạy nền
from app.services.scheduler import scheduler_loop, execute_schedule_action, TZ
from app.services.vn_time_parser import resolve_target_days

# Tạm thời comment Automation Engine để tránh lỗi chưa hoàn thiện
# from app.services.automation_engine import automation_engine, AutomationRule

# Import Database + Auth
from app.core.database import get_db, init_db
from app.core.auth import get_current_user, require_admin, CurrentUser
from app.core.crypto import encrypt_json
from app.models.device import DeviceModel
from app.models.schedule import ScheduleModel        # đăng ký bảng schedules với Base
from app.models.vendor_account import VendorAccountModel

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
init_db()  # SQLite: create_all + ALTER cột thiếu. Postgres: schema qua SQL file.

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

    # Tuya/Rojeco dùng chung 1 project (token chung) -> singleton toàn app.
    # VeSync KHÔNG khởi tạo ở đây nữa: mỗi user 1 tài khoản riêng, connector
    # tạo lười theo user qua connector_factory khi có lệnh.
    await _init_connector("tuya", TuyaConnector)
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

# App mobile native không bị ràng buộc CORS; nếu dùng web thì set ALLOWED_ORIGINS
# (CSV) trong env. Dùng Bearer token (không dùng cookie) nên allow_credentials=False.
_allowed = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# Helper thiết bị (serialize + kiểm tra sở hữu)
# =========================================================
def _device_to_dict(d: DeviceModel) -> dict:
    return {
        "id": d.id, "name": d.name, "brand": d.brand,
        "category": d.category, "is_active": bool(d.is_active),
        "sort_order": d.sort_order or 0,
    }

def _get_owned_device(db: Session, user: CurrentUser, device_id: str) -> DeviceModel:
    """Lấy thiết bị THUỘC user hiện tại; 404 nếu không có/không phải của họ."""
    dev = (db.query(DeviceModel)
             .filter(DeviceModel.id == device_id,
                     DeviceModel.user_id == user.user_id)
             .first())
    if not dev:
        raise HTTPException(404, "Không tìm thấy thiết bị của bạn.")
    return dev

# =========================================================
# API - Get Devices (scope theo user)
# =========================================================
@app.get("/api/devices")
async def get_all_devices(user: CurrentUser = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    devices = (db.query(DeviceModel)
                 .filter(DeviceModel.user_id == user.user_id)
                 .order_by(DeviceModel.sort_order, DeviceModel.name)
                 .all())
    return {"status": "success", "data": [_device_to_dict(d) for d in devices]}

# =========================================================
# API - Add & Delete Device
# =========================================================
@app.post("/api/devices")
async def add_device(id: str, name: str, brand: str,
                     user: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    try:
        existing = db.query(DeviceModel).filter(DeviceModel.id == id).first()
        if existing:
            if existing.user_id != user.user_id:
                return {"status": "error", "message": "Thiết bị đã thuộc người dùng khác."}
            return {"status": "success", "message": "Thiết bị đã có sẵn."}
        new_device = DeviceModel(id=id, user_id=user.user_id, name=name,
                                 brand=brand, is_active=True)
        db.add(new_device)
        db.commit()
        logger.info(f"Đã thêm thiết bị mới: {name} ({brand}) cho user {user.user_id}")
        return {"status": "success", "message": f"Đã thêm: {name}"}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi thêm thiết bị: {e}")
        return {"status": "error", "message": f"Lỗi: {str(e)}"}

@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: str,
                        user: CurrentUser = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    try:
        device = (db.query(DeviceModel)
                    .filter(DeviceModel.id == device_id,
                            DeviceModel.user_id == user.user_id)
                    .first())
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
# CACHE TRẠNG THÁI NGẮN HẠN (key theo user để không rò rỉ giữa các user)
# =========================================================
_STATUS_CACHE_TTL = 3.0  # giây
_status_cache: dict = {}  # {(user_id, brand, device_id): (monotonic_ts, data)}

def _cache_get(user_id: str, brand: str, device_id: str):
    entry = _status_cache.get((user_id, brand, device_id))
    if entry and (time.monotonic() - entry[0]) < _STATUS_CACHE_TTL:
        return entry[1]
    return None

def _cache_set(user_id: str, brand: str, device_id: str, data):
    _status_cache[(user_id, brand, device_id)] = (time.monotonic(), data)

def _cache_invalidate(user_id: str, brand: str, device_id: str):
    _status_cache.pop((user_id, brand, device_id), None)

# =========================================================
# API - Test Control Device (Action & Mode)
# =========================================================
@app.get("/api/test-control/{brand}/{device_id}")
async def test_control(brand: str, device_id: str, action: str = "on",
                       user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    try:
        _get_owned_device(db, user, device_id)  # 404 nếu không phải thiết bị của user
        connector = await connector_factory.get_user_connector(db, user.user_id, brand)
        if action == "on":
            ok = await connector.turn_on(device_id)
        else:
            ok = await connector.turn_off(device_id)
        _cache_invalidate(user.user_id, brand, device_id)
        if not ok:
            logger.warning(f"Lệnh {action} cho {device_id} qua {brand} không thành công")
            return {"status": "error", "message": f"Thiết bị {device_id} không nhận lệnh {action}"}
        logger.info(f"Đã thực hiện lệnh {action} cho thiết bị {device_id} qua {brand}")
        return {"status": "success", "message": f"Đã {action} thiết bị {device_id} ({brand})"}
    except HTTPException:
        raise
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Lỗi điều khiển {brand}: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/test-control/{brand}/{device_id}/mode")
async def test_control_mode(brand: str, device_id: str, mode: str,
                            user: CurrentUser = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    try:
        _get_owned_device(db, user, device_id)
        connector = await connector_factory.get_user_connector(db, user.user_id, brand)
        if hasattr(connector, 'set_mode'):
            ok = await connector.set_mode(device_id, mode)
            _cache_invalidate(user.user_id, brand, device_id)
            if not ok:
                logger.warning(f"Đổi chế độ {mode} cho {device_id} qua {brand} không thành công")
                return {"status": "error", "message": f"Thiết bị không nhận chế độ {mode}"}
            logger.info(f"Đã chuyển chế độ {mode} cho thiết bị {device_id} qua {brand}")
            return {"status": "success", "message": f"Đã chuyển sang chế độ {mode}"}
        else:
            return {"status": "error", "message": "Thiết bị không hỗ trợ đổi chế độ"}
    except HTTPException:
        raise
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Lỗi đổi chế độ {brand}: {e}")
        return {"status": "error", "message": str(e)}

# =========================================================
# API - Lấy trạng thái THẬT của thiết bị (query từ phần cứng)
# =========================================================
@app.get("/api/devices/{brand}/{device_id}/status")
async def get_device_status(brand: str, device_id: str, fresh: bool = False,
                            user: CurrentUser = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    try:
        _get_owned_device(db, user, device_id)
        # fresh=1: bỏ qua cache (client gọi ngay sau lệnh điều khiển để lấy
        # trạng thái mới nhất). Poll định kỳ vẫn dùng cache bình thường.
        if not fresh:
            cached = _cache_get(user.user_id, brand, device_id)
            if cached is not None:
                return {"status": "success", "data": cached, "cached": True}
        connector = await connector_factory.get_user_connector(db, user.user_id, brand)
        if not connector:
            return {"status": "error", "message": f"Không tìm thấy connector cho {brand}"}
        state = await connector.get_device_state(device_id)
        _cache_set(user.user_id, brand, device_id, state)
        return {"status": "success", "data": state}
    except HTTPException:
        raise
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Lỗi lấy trạng thái {brand}/{device_id}: {e}")
        return {"status": "error", "message": str(e)}

# =========================================================
# API - Tài khoản người dùng
# =========================================================
@app.get("/api/me")
async def get_me(user: CurrentUser = Depends(get_current_user)):
    return {"status": "success", "data": {
        "user_id": user.user_id, "email": user.email, "is_admin": user.is_admin,
    }}

# =========================================================
# Helper: vendor account + import thiết bị
# =========================================================
def _upsert_vendor_account(db: Session, user_id: str, brand: str, *,
                           credentials: dict | None = None, tuya_uid: str | None = None,
                           label: str = "", status: str = "connected") -> VendorAccountModel:
    acc = (db.query(VendorAccountModel)
             .filter(VendorAccountModel.user_id == user_id,
                     VendorAccountModel.brand == brand).first())
    if not acc:
        acc = VendorAccountModel(user_id=user_id, brand=brand)
        db.add(acc)
    if credentials is not None:
        acc.credentials_encrypted = encrypt_json(credentials)
    if tuya_uid is not None:
        acc.tuya_uid = tuya_uid
    if label:
        acc.label = label
    acc.status = status
    db.commit()
    db.refresh(acc)
    return acc

def _import_devices_for(db: Session, user_id: str, items: list) -> dict:
    """Thêm hàng loạt thiết bị cho user_id. Bỏ qua thiết bị đã thuộc user KHÁC."""
    added, skipped = 0, 0
    for it in items:
        did = (it.get("id") or "").strip()
        if not did:
            skipped += 1
            continue
        existing = db.query(DeviceModel).filter(DeviceModel.id == did).first()
        if existing:
            skipped += 1
            continue
        db.add(DeviceModel(
            id=did, user_id=user_id, name=(it.get("name") or did),
            brand=(it.get("brand") or "").lower() or "tuya",
            category=it.get("category"), is_active=True,
        ))
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}

def _map_tuya_device(d: dict) -> dict:
    cat = d.get("category") or ""
    # Máy cho ăn thú cưng (cwwsq...) -> gợi ý brand rojeco; còn lại tuya.
    suggested = "rojeco" if str(cat).startswith("cww") else "tuya"
    return {
        "id": d.get("id"), "name": d.get("name") or d.get("id"),
        "category": cat, "product_name": d.get("product_name"),
        "online": d.get("online"), "suggested_brand": suggested,
    }

# =========================================================
# API - Kết nối nhà cung cấp & khám phá thiết bị
# =========================================================
class VeSyncConnect(BaseModel):
    email: str
    password: str

class ImportItem(BaseModel):
    id: str
    name: str | None = None
    brand: str
    category: str | None = None

class ImportBody(BaseModel):
    devices: list[ImportItem]

@app.get("/api/vendor/accounts")
async def list_vendor_accounts(user: CurrentUser = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    accs = db.query(VendorAccountModel).filter(VendorAccountModel.user_id == user.user_id).all()
    return {"status": "success", "data": [{
        "brand": a.brand, "label": a.label, "status": a.status,
        "has_tuya_uid": bool(a.tuya_uid),
    } for a in accs]}

@app.post("/api/vendor/vesync/connect")
async def vesync_connect(body: VeSyncConnect,
                         user: CurrentUser = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Đăng nhập VeSync, trả danh sách thiết bị để user chọn. Lưu credential mã hóa."""
    try:
        devices = await connector_factory.discover_vesync(body.email, body.password)
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"[VeSync Connect] {e}")
        return {"status": "error", "message": "Lỗi kết nối VeSync."}
    _upsert_vendor_account(db, user.user_id, "vesync",
                           credentials={"email": body.email, "password": body.password},
                           label=body.email)
    connector_factory.invalidate_user(user.user_id)  # buộc dùng creds mới
    return {"status": "success", "data": [{
        "id": d["cid"], "name": d["name"], "brand": "vesync",
        "device_type": d["device_type"],
    } for d in devices if d.get("cid")]}

@app.post("/api/devices/import")
async def import_devices(body: ImportBody,
                         user: CurrentUser = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    result = _import_devices_for(db, user.user_id, [i.model_dump() for i in body.devices])
    logger.info(f"Import thiết bị cho {user.user_id}: {result}")
    return {"status": "success", "data": result}

@app.get("/api/vendor/tuya/link-info")
async def tuya_link_info(user: CurrentUser = Depends(get_current_user)):
    """Hướng dẫn liên kết tài khoản Tuya/Smart Life vào project (QR ở Tuya console)."""
    return {"status": "success", "data": {
        "steps": [
            "Mở app Smart Life / Tuya Smart trên điện thoại.",
            "Vào Tôi (Me) → Cài đặt (⚙) → quét mã QR.",
            "Quét mã QR 'Link App Account' mà quản trị viên cung cấp (từ Tuya IoT console).",
            "Xác nhận đăng nhập. Sau đó báo quản trị viên để gán thiết bị của bạn vào tài khoản.",
        ],
        "note": "Do Tuya không còn API đăng nhập email/mật khẩu, bước liên kết QR này cần quản trị viên hỗ trợ 1 lần.",
    }}

@app.post("/api/vendor/tuya/discover")
async def tuya_discover(user: CurrentUser = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Liệt kê thiết bị Tuya của user (cần đã có tuya_uid do admin gán)."""
    acc = (db.query(VendorAccountModel)
             .filter(VendorAccountModel.user_id == user.user_id,
                     VendorAccountModel.brand == "tuya").first())
    if not acc or not acc.tuya_uid:
        return {"status": "error",
                "message": "Chưa liên kết Tuya. Hãy quét QR & nhờ quản trị viên gán tài khoản."}
    try:
        tuya = device_manager.get_connector("tuya")
        raw = await tuya.list_user_devices(acc.tuya_uid)
        return {"status": "success", "data": [_map_tuya_device(d) for d in raw]}
    except Exception as e:
        logger.error(f"[Tuya Discover] {e}")
        return {"status": "error", "message": "Lỗi lấy thiết bị Tuya."}

# =========================================================
# API - Admin (chỉ role admin)
# =========================================================
class AdminImportBody(BaseModel):
    user_id: str
    devices: list[ImportItem]

class TuyaAssignBody(BaseModel):
    user_id: str
    tuya_uid: str

@app.get("/api/admin/users")
async def admin_list_users(_: CurrentUser = Depends(require_admin),
                           db: Session = Depends(get_db)):
    from sqlalchemy import func, text as _text
    from app.core.database import IS_SQLITE
    # Đếm thiết bị theo user
    counts = dict(db.query(DeviceModel.user_id, func.count(DeviceModel.id))
                    .group_by(DeviceModel.user_id).all())
    users = []
    if not IS_SQLITE:
        rows = db.execute(_text(
            "select id::text as id, email, display_name, role from public.profiles order by created_at"
        )).mappings().all()
        for r in rows:
            users.append({"user_id": r["id"], "email": r["email"],
                          "display_name": r["display_name"], "role": r["role"],
                          "device_count": counts.get(r["id"], 0)})
    else:
        for uid, cnt in counts.items():
            users.append({"user_id": uid, "email": None, "display_name": None,
                          "role": None, "device_count": cnt})
    return {"status": "success", "data": users}

@app.get("/api/admin/users/{target_user_id}/devices")
async def admin_user_devices(target_user_id: str,
                             _: CurrentUser = Depends(require_admin),
                             db: Session = Depends(get_db)):
    devices = db.query(DeviceModel).filter(DeviceModel.user_id == target_user_id).all()
    return {"status": "success", "data": [_device_to_dict(d) for d in devices]}

@app.post("/api/admin/devices/import")
async def admin_import_devices(body: AdminImportBody,
                               _: CurrentUser = Depends(require_admin),
                               db: Session = Depends(get_db)):
    result = _import_devices_for(db, body.user_id, [i.model_dump() for i in body.devices])
    return {"status": "success", "data": result}

@app.get("/api/admin/tuya/linked")
async def admin_tuya_linked(_: CurrentUser = Depends(require_admin)):
    """Liệt kê các tài khoản Tuya đã liên kết vào project + thiết bị của từng account."""
    schema = os.getenv("TUYA_APP_SCHEMA", "").strip()
    if not schema:
        return {"status": "error", "message": "Chưa cấu hình TUYA_APP_SCHEMA trong env."}
    try:
        tuya = device_manager.get_connector("tuya")
        users = await tuya.list_app_users(schema)
        out = []
        for u in users:
            uid = u.get("uid") or u.get("user_id")
            devs = await tuya.list_user_devices(uid) if uid else []
            out.append({"uid": uid, "raw": u,
                        "devices": [_map_tuya_device(d) for d in devs]})
        return {"status": "success", "data": out}
    except Exception as e:
        logger.error(f"[Admin Tuya Linked] {e}")
        return {"status": "error", "message": "Lỗi lấy danh sách tài khoản Tuya."}

@app.post("/api/admin/vendor/tuya/assign")
async def admin_tuya_assign(body: TuyaAssignBody,
                            _: CurrentUser = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Gán 1 tuya_uid (tài khoản Tuya đã liên kết) cho 1 app user."""
    _upsert_vendor_account(db, body.user_id, "tuya", tuya_uid=body.tuya_uid,
                           label=f"uid:{body.tuya_uid[:8]}")
    return {"status": "success", "message": "Đã gán tài khoản Tuya cho người dùng."}

# =========================================================
# API - Nhận Lệnh Giọng Nói (AI OpenRouter)
# =========================================================
def _action_label_vn(action_type: str, action_value: str | None) -> str:
    """Nhãn tiếng Việt cho 1 hành động — dùng chung cho thi hành ngay lẫn hẹn giờ."""
    if action_type in ("on", "turn_on"):
        return "Bật"
    if action_type in ("off", "turn_off"):
        return "Tắt"
    if action_value == "open":
        return "Mở"
    if action_value == "close":
        return "Đóng"
    if action_value == "stop":
        return "Dừng"
    return f"Chế độ {action_value}"

def _verb_to_schedule_action(verb: str | None, mode: str | None) -> tuple[str | None, str | None]:
    """Đổi từ vựng parser (turn_on/turn_off/set_mode | on/off) -> cột lịch (on/off/mode)."""
    if verb in ("on", "turn_on"):
        return "on", None
    if verb in ("off", "turn_off"):
        return "off", None
    if verb == "set_mode" or mode:
        return "mode", mode
    return None, None

def _create_schedule_from_intent(action: dict, devices: list, db: Session, user_id: str) -> dict:
    """
    Tạo lịch hẹn từ intent 'schedule' của local parser / AI.
    Trả về bubble chat {"device_name","action","success"} — KHÔNG chạm connector.
    """
    dev_id = action.get("id")
    device_obj = next((d for d in devices if d.id == dev_id), None)
    dev_name = device_obj.name if device_obj else dev_id
    try:
        action_type, action_value = _verb_to_schedule_action(action.get("action"), action.get("mode"))
        if not action_type:
            raise ValueError("không rõ hành động")
        end_time = action.get("end_time")
        end_action_type = end_action_value = None
        if end_time:
            end_action_type, end_action_value = _verb_to_schedule_action(
                action.get("end_action"), action.get("end_mode"))
            if not end_action_type:
                end_time = None  # khoảng không có hành động kết thúc hợp lệ -> lịch đơn

        days, one_shot, rolled = resolve_target_days(
            action.get("time", ""), int(action.get("day_offset", 0) or 0),
            bool(action.get("recurring_daily", False)), datetime.now(TZ),
        )
        sch = _create_schedule_row(
            db, user_id=user_id, name="Tạo bởi trợ lý", brand=action.get("brand"), device_id=dev_id,
            action_type=action_type, action_value=action_value,
            time=action.get("time", ""), days=days,
            end_time=end_time, end_action_type=end_action_type,
            end_action_value=end_action_value, one_shot=one_shot,
        )
        prefix = "ngày mai " if (rolled or int(action.get("day_offset", 0) or 0) > 0) else ""
        label = _action_label_vn(action_type, action_value)
        if sch.end_time:
            end_label = _action_label_vn(end_action_type, end_action_value)
            action_ui = f"Đã hẹn {prefix}{sch.time}→{sch.end_time} • {label}, kết thúc: {end_label}"
        else:
            action_ui = f"Đã hẹn {prefix}{sch.time} • {label}"
        if not days and not one_shot:
            action_ui += " (mỗi ngày)"
        return {"device_name": dev_name, "action": action_ui, "success": True}
    except ValueError as e:
        return {"device_name": dev_name, "action": f"Lỗi hẹn giờ: {e}", "success": False}
    except Exception as e:
        db.rollback()
        logger.error(f"[AI Schedule Error] {e}")
        return {"device_name": dev_name, "action": "Lỗi hẹn giờ: không tạo được lịch", "success": False}

class VoiceCommand(BaseModel):
    text: str

@app.post("/api/ai/parse")
async def parse_voice_command(command: VoiceCommand,
                              user: CurrentUser = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    # Depends(get_db): session tự đóng kể cả khi query lỗi — tránh leak.
    devices = db.query(DeviceModel).filter(DeviceModel.user_id == user.user_id).all()

    text_lower = command.text.lower()
    logger.info(f"Nhận lệnh giọng nói: '{command.text}'")
    actions = []
    
    # ---------------------------------------------------------
    # BỨC TƯỜNG LỬA: KIỂM TRA TỪ KHÓA THIẾT BỊ
    # ---------------------------------------------------------
    # Danh sách các từ khóa liên quan đến thiết bị trong nhà
    device_keywords = ["quạt", "lọc", "không khí", "mèo", "ăn", "hạt", "cửa", "cuốn", "đèn", "tất cả",
                       "hẹn", "lịch"]  # từ khóa hẹn giờ: cho câu tạo lịch đi qua tường lửa
    
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
        # Ý ĐỊNH HẸN GIỜ: tạo lịch trong DB, TUYỆT ĐỐI không gọi connector.
        if action.get("intent") == "schedule":
            return _create_schedule_from_intent(action, devices, db, user.user_id)

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

        if is_on or is_off or mode:
            action_ui = _action_label_vn("on" if is_on else "off" if is_off else "mode", mode)
        else:
            action_ui = "Thực thi"

        success = False
        try:
            # Chỉ điều khiển thiết bị THUỘC user (devices đã scope theo user_id).
            connector = await connector_factory.get_user_connector(db, user.user_id, brand)
            if connector:
                if is_off:
                    success = await connector.turn_off(dev_id)
                elif is_on:
                    success = await connector.turn_on(dev_id)
                elif mode and hasattr(connector, 'set_mode'):
                    success = await connector.set_mode(dev_id, mode)
            # FIX: invalidate cache như các endpoint control — để lần đọc
            # trạng thái kế tiếp không dính bản cache cũ (~3s).
            _cache_invalidate(user.user_id, brand, dev_id)
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
    end_time: str | None = None          # lịch KHOẢNG: giờ kết thúc; end < time = qua đêm
    end_action_type: str | None = None   # bắt buộc khi có end_time
    end_action_value: str | None = None
    one_shot: bool = False               # chạy 1 lần rồi tự tắt

class ScheduleUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    device_id: str | None = None
    action_type: str | None = None
    action_value: str | None = None
    time: str | None = None
    days: str | None = None
    enabled: bool | None = None
    end_time: str | None = None          # gửi null tường minh để xóa khoảng
    end_action_type: str | None = None
    end_action_value: str | None = None
    one_shot: bool | None = None

_TIME_FMT_RE = r"([01]?\d|2[0-3]):[0-5]\d"

def _hhmm_to_minutes(t: str) -> int:
    hh, mm = t.split(":")
    return int(hh) * 60 + int(mm)

def _validate_schedule_fields(action_type: str | None, action_value: str | None,
                              time_str: str | None, days: str | None,
                              end_time: str | None = None,
                              end_action_type: str | None = None,
                              end_action_value: str | None = None) -> str | None:
    """Trả về thông báo lỗi (tiếng Việt) hoặc None nếu hợp lệ."""
    if action_type is not None:
        if action_type not in ("on", "off", "mode"):
            return "action_type phải là on | off | mode"
        if action_type == "mode" and not action_value:
            return "action_value bắt buộc khi action_type = mode"
    if time_str is not None and not _re.fullmatch(_TIME_FMT_RE, time_str):
        return "time phải có dạng HH:MM (00:00–23:59)"
    if days:
        parts = [p.strip() for p in days.split(",") if p.strip()]
        if any(not p.isdigit() or int(p) > 6 for p in parts):
            return "days phải là CSV các số 0-6 (0=Thứ2 … 6=CN)"
    # --- Lịch KHOẢNG: bộ end validate cùng luật với start ---
    if end_time is not None:
        if not end_action_type:
            return "Lịch khoảng cần đủ giờ kết thúc và hành động kết thúc"
        if end_action_type not in ("on", "off", "mode"):
            return "end_action_type phải là on | off | mode"
        if end_action_type == "mode" and not end_action_value:
            return "end_action_value bắt buộc khi end_action_type = mode"
        if not _re.fullmatch(_TIME_FMT_RE, end_time):
            return "end_time phải có dạng HH:MM (00:00–23:59)"
        # end < start hợp lệ (khoảng QUA ĐÊM, end thuộc hôm sau); chỉ chặn trùng giờ.
        if time_str and _hhmm_to_minutes(end_time) == _hhmm_to_minutes(time_str):
            return "Giờ kết thúc phải khác giờ bắt đầu"
    elif end_action_type is not None:
        return "Lịch khoảng cần đủ giờ kết thúc và hành động kết thúc"
    return None

def _create_schedule_row(db: Session, *, user_id: str, name: str, brand: str, device_id: str,
                         action_type: str, action_value: str | None, time: str,
                         days: str = "", enabled: bool = True,
                         end_time: str | None = None, end_action_type: str | None = None,
                         end_action_value: str | None = None,
                         one_shot: bool = False) -> ScheduleModel:
    """Validate + tạo 1 lịch. Dùng chung cho POST /api/schedules và trợ lý AI.
    Lỗi validate -> raise ValueError(thông báo tiếng Việt)."""
    err = _validate_schedule_fields(action_type, action_value, time, days,
                                    end_time, end_action_type, end_action_value)
    if err:
        raise ValueError(err)
    sch = ScheduleModel(
        user_id=user_id, name=name, brand=brand, device_id=device_id,
        action_type=action_type, action_value=action_value,
        time=time, days=days, enabled=enabled,
        end_time=end_time, end_action_type=end_action_type,
        end_action_value=end_action_value, one_shot=one_shot,
    )
    db.add(sch)
    db.commit()
    db.refresh(sch)
    logger.info(f"⏰ Đã tạo lịch #{sch.id}: {sch.brand}/{sch.device_id} {sch.action_type} lúc {sch.time}"
                + (f" → {sch.end_action_type} lúc {sch.end_time}" if sch.end_time else ""))
    return sch

def _schedule_to_dict(s: ScheduleModel) -> dict:
    return {
        "id": s.id, "name": s.name, "brand": s.brand, "device_id": s.device_id,
        "action_type": s.action_type, "action_value": s.action_value,
        "time": s.time, "days": s.days or "", "enabled": bool(s.enabled),
        "last_fired_date": s.last_fired_date,
        "end_time": s.end_time, "end_action_type": s.end_action_type,
        "end_action_value": s.end_action_value,
        "last_end_fired_date": s.last_end_fired_date,
        "one_shot": bool(s.one_shot),
    }

@app.get("/api/schedules")
async def list_schedules(user: CurrentUser = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    schedules = (db.query(ScheduleModel)
                   .filter(ScheduleModel.user_id == user.user_id)
                   .order_by(ScheduleModel.time).all())
    return {"status": "success", "data": [_schedule_to_dict(s) for s in schedules]}

@app.post("/api/schedules")
async def create_schedule(body: ScheduleCreate,
                          user: CurrentUser = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    try:
        _get_owned_device(db, user, body.device_id)  # chỉ hẹn cho thiết bị của mình
        sch = _create_schedule_row(
            db, user_id=user.user_id, name=body.name, brand=body.brand, device_id=body.device_id,
            action_type=body.action_type, action_value=body.action_value,
            time=body.time, days=body.days, enabled=body.enabled,
            end_time=body.end_time, end_action_type=body.end_action_type,
            end_action_value=body.end_action_value, one_shot=body.one_shot,
        )
        return {"status": "success", "data": _schedule_to_dict(sch)}
    except HTTPException:
        raise
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi tạo lịch: {e}")
        return {"status": "error", "message": str(e)}

@app.patch("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, body: ScheduleUpdate,
                          user: CurrentUser = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    sch = (db.query(ScheduleModel)
             .filter(ScheduleModel.id == schedule_id,
                     ScheduleModel.user_id == user.user_id).first())
    if not sch:
        return {"status": "error", "message": "Không tìm thấy lịch."}
    fields = body.model_dump(exclude_unset=True)
    # Validate trên giá trị ĐÃ MERGE (giá trị mới nếu có, không thì giá trị hiện tại)
    # để so chéo start/end chính xác với PATCH từng phần.
    merged = {k: fields.get(k, getattr(sch, k))
              for k in ("action_type", "action_value", "time", "days",
                        "end_time", "end_action_type", "end_action_value")}
    err = _validate_schedule_fields(
        merged["action_type"], merged["action_value"], merged["time"], merged["days"],
        merged["end_time"], merged["end_action_type"], merged["end_action_value"],
    )
    if err:
        return {"status": "error", "message": err}
    try:
        for key, value in fields.items():
            setattr(sch, key, value)
        # Đổi giờ/bật lại lịch -> cho phép kích hoạt lại trong hôm nay nếu tới giờ mới.
        if "time" in fields or fields.get("enabled") is True:
            sch.last_fired_date = None
        if "end_time" in fields or fields.get("enabled") is True:
            sch.last_end_fired_date = None
        # Xóa khoảng (end_time: null tường minh) -> dọn sạch cả bộ end cho nhất quán.
        if "end_time" in fields and fields["end_time"] is None:
            sch.end_action_type = None
            sch.end_action_value = None
            sch.last_end_fired_date = None
        db.commit()
        db.refresh(sch)
        return {"status": "success", "data": _schedule_to_dict(sch)}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi sửa lịch #{schedule_id}: {e}")
        return {"status": "error", "message": str(e)}

@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int,
                          user: CurrentUser = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    sch = (db.query(ScheduleModel)
             .filter(ScheduleModel.id == schedule_id,
                     ScheduleModel.user_id == user.user_id).first())
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
async def run_schedule_now(schedule_id: int, part: str = "start",
                           user: CurrentUser = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """Chạy NGAY hành động của lịch (để test), không ảnh hưởng last_fired_date.
    part=end: chạy hành động KẾT THÚC của lịch khoảng."""
    sch = (db.query(ScheduleModel)
             .filter(ScheduleModel.id == schedule_id,
                     ScheduleModel.user_id == user.user_id).first())
    if not sch:
        return {"status": "error", "message": "Không tìm thấy lịch."}
    if part == "end" and not sch.end_time:
        return {"status": "error", "message": "Lịch này không có hành động kết thúc."}
    action_type = sch.end_action_type if part == "end" else sch.action_type
    action_value = sch.end_action_value if part == "end" else sch.action_value
    try:
        ok = await execute_schedule_action(
            db, sch.user_id, sch.brand, sch.device_id, action_type, action_value,
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