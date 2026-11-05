# backend/app/main.py

import sys
import os
import asyncio
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Nạp biến môi trường từ backend/.env TRƯỚC khi import các connector
# (credential Tuya/VeSync/Rojeco đọc từ os.getenv lúc khởi tạo).
load_dotenv()

from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, Depends, HTTPException, status
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session

# Import các Connector và Manager
from app.services.local_parser import match_scene, parse_command_locally
from app.services.connector_manager import device_manager
from app.services.tuya_connector import TuyaConnector
from app.services.vesync_connector import VeSyncConnector
from app.services.rojeco_connector import RojecoConnector

# Import AI Parser (Đã đổi thành AI dùng cho OpenRouter)
from app.services.ai_parser import parse_command_with_ai

# Vòng lặp Hẹn giờ chạy nền
from app.services.scheduler import scheduler_loop, execute_schedule_action, TZ
from app.services import command_log, device_history
from app.models.command_log import CommandLogModel
from app.services.vn_time_parser import resolve_target_days
from app.services.device_actions import normalize_action

# Tạm thời comment Automation Engine để tránh lỗi chưa hoàn thiện
# from app.services.automation_engine import automation_engine, AutomationRule

# Import Database
from app.core.auth import app_token_secret, auth_status, issue_app_token
from app.core.database import SessionLocal, get_db, init_db, IS_SQLITE
from app.core.household import (
    accessible_zones,
    device_query,
    get_current_member,
    get_member,
    member_to_dict,
    require_can_schedule,
    require_device_access,
    require_owner,
    require_scene_write,
    require_schedule_write,
    schedule_query,
    zone_ids_of,
)
from app.models.member import ROLES, STATUSES, MemberModel
from app.models.zone import MemberZoneAccessModel, ZoneModel
from app.models.device import DEVICE_CATEGORIES, DeviceModel, device_kind
from app.models.schedule import ScheduleModel  # đăng ký bảng schedules với Base
from app.models.scene import SceneModel

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
# ⚠️ KHÔNG khởi tạo DB ở tầng import: exception ở đây làm uvicorn chết với
# "Error loading ASGI app" — không route nào chạy, kể cả /health, nên không thể
# phân biệt "lỗi DB" với "app chết". Việc này được gọi trong lifespan (bọc
# try/except) để app còn boot ở chế độ degraded và /health nói rõ nguyên nhân.
db_ready = False


# init_db() nằm ở app/core/database.py: create_all -> thêm cột thiếu -> bật RLS
# (Postgres) -> seed thiết bị nếu rỗng -> verify_schema (raise nếu lệch).

# =========================================================
# Lifespan: khởi động connector + vòng lặp Hẹn giờ (Scheduler)
# =========================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_ready
    logger.info("Đang khởi tạo Database (%s)...", "SQLite" if IS_SQLITE else "Postgres")
    try:
        init_db()
        db_ready = True
        logger.info("✅ Database sẵn sàng.")
        if IS_SQLITE:
            # Trên Render ổ đĩa là ephemeral: container dựng lại mỗi lần deploy
            # nên file SQLite bị ghi đè -> lịch hẹn của người dùng mất sạch.
            logger.warning(
                "⚠️ Đang dùng SQLite. Nếu đây là Render, lịch hẹn sẽ MẤT mỗi lần "
                "deploy — đặt DATABASE_URL trỏ tới Postgres (xem docs/SUPABASE_SETUP.md)."
            )
    except Exception as e:
        # Boot degraded: /health vẫn trả lời để UptimeRobot không flatline và
        # để log nói rõ đây là lỗi DB, không phải app chết.
        logger.error(f"❌ Khởi tạo DB thất bại — app chạy ở chế độ degraded: {e}")

    # Xác thực: nói to lúc boot. Chạy mở mà không ai biết là kịch bản tệ nhất.
    auth_on, why = auth_status()
    if auth_on:
        logger.info("🔒 Xác thực BẬT (%s).", why)
        if not app_token_secret():
            logger.error(
                "❌ Xác thực BẬT nhưng THIẾU APP_TOKEN_SECRET — Home Widget và shortcut "
                "sẽ hỏng âm thầm (không cấp được app-token). Đặt APP_TOKEN_SECRET trên Render."
            )
    else:
        logger.warning(
            "🔓 Xác thực TẮT (%s) — mọi request được coi là chủ nhà. "
            "Đúng cho giai đoạn chưa gắn đăng nhập; đặt SUPABASE_URL để bật.",
            why,
        )

    logger.info("Bắt đầu khởi động các connector...")

    async def _init_connector(brand: str, factory):
        """Khởi tạo 1 connector an toàn: lỗi 1 hãng không làm sập cả app."""
        try:
            plugin = factory()
            # Đăng ký TRƯỚC khi connect: connect lỗi thì connector vẫn có mặt
            # và tự thử lại khi có lệnh, thay vì "chưa hỗ trợ hãng" tới khi restart.
            device_manager.register_connector(brand, plugin)
            ok = await plugin.connect()
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
    # DB chết thì KHÔNG chạy scheduler: tick 30s sẽ log stack trace vĩnh viễn.
    scheduler_task = (
        asyncio.create_task(scheduler_loop(invalidate_cache=_cache_invalidate))
        if db_ready else None
    )
    if scheduler_task is None:
        logger.warning("⏰ Scheduler KHÔNG khởi động vì DB chưa sẵn sàng.")

    yield

    # Shutdown: dừng scheduler sạch sẽ
    if scheduler_task is not None:
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
class DeviceUpdate(BaseModel):
    """PATCH /api/devices/{id} — chỉ field nào gửi mới được sửa (exclude_unset)."""
    name: str | None = None
    zone_id: int | None = None   # null tường minh = đưa về "hộp thư đến"
    category: str | None = None


class ZoneCreate(BaseModel):
    name: str
    sort_order: int = 0
    is_shared: bool = False


class ZoneUpdate(BaseModel):
    name: str | None = None
    sort_order: int | None = None
    is_shared: bool | None = None


def _zone_to_dict(z: ZoneModel) -> dict:
    return {"id": z.id, "name": z.name, "sort_order": z.sort_order, "is_shared": bool(z.is_shared)}


class MeUpdate(BaseModel):
    """PATCH /api/me — chỉ thông tin hiển thị của CHÍNH MÌNH, không có vai/trạng thái."""
    display_name: str | None = None
    avatar_color: str | None = None  # "#RRGGBB"; null tường minh = về màu tự động


class MemberUpdate(BaseModel):
    """PATCH /api/members/{user_id} — zone_ids thay CẢ BỘ, không phải add/remove."""
    role: str | None = None
    status: str | None = None
    display_name: str | None = None
    zone_ids: list[int] | None = None


def _device_to_dict(d: DeviceModel, zone: ZoneModel | None = None) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "brand": d.brand,
        "is_active": d.is_active,
        "zone_id": d.zone_id,
        "zone_name": zone.name if zone else None,
        "zone_shared": bool(zone.is_shared) if zone else False,
        "category": d.category,
    }


@app.get("/api/devices")
async def get_all_devices(
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    # device_query đã lọc theo khu được cấp — kid/guest không thấy khu khác,
    # và thiết bị chưa phân khu (zone_id NULL) tự rơi ra ngoài INNER JOIN.
    rows = (
        device_query(db, member)
        .outerjoin(ZoneModel, ZoneModel.id == DeviceModel.zone_id)
        .with_entities(DeviceModel, ZoneModel)
        .order_by(ZoneModel.sort_order, DeviceModel.name)
        .all()
    )
    return {"status": "success", "data": [_device_to_dict(d, z) for d, z in rows]}

# =========================================================
# API - Add & Delete Device (chỉ chủ nhà)
# =========================================================
@app.post("/api/devices")
async def add_device(
    id: str,
    name: str,
    brand: str,
    zone_id: int | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(require_owner),
):
    # Thiết bị mới thiếu category sẽ bị suy loại theo tên/hãng — một công tắc
    # Tuya tên lạ thành "cửa cuốn". Cho đặt ngay lúc thêm.
    if category is not None and category not in DEVICE_CATEGORIES:
        return {"status": "error", "message": f"Loại không hợp lệ. Hợp lệ: {list(DEVICE_CATEGORIES)}"}
    try:
        # Idempotent: thêm lại id đã có = "đã có trong nhà", không phải lỗi.
        # Client retry (mạng chập chờn) không nên báo đỏ.
        existing = db.query(DeviceModel).filter(DeviceModel.id == id).first()
        if existing:
            return {"status": "success", "message": f"Thiết bị đã có trong nhà: {existing.name}"}

        if zone_id is not None and not db.query(ZoneModel).filter(ZoneModel.id == zone_id).first():
            return {"status": "error", "message": "Khu vực không tồn tại."}

        db.add(DeviceModel(id=id, name=name, brand=brand, is_active=True, zone_id=zone_id,
                           category=category))
        db.commit()
        logger.info(f"Đã thêm thiết bị mới: {name} ({brand})")
        return {"status": "success", "message": f"Đã thêm: {name}"}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi thêm thiết bị: {e}")
        return {"status": "error", "message": f"Lỗi: {str(e)}"}


@app.patch("/api/devices/{device_id}")
async def update_device(
    device_id: str,
    body: DeviceUpdate,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(require_owner),
):
    """Đổi tên / gán khu vực / đặt loại. Đây là cách thiết bị được gán phòng."""
    device = db.query(DeviceModel).filter(DeviceModel.id == device_id).first()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thiết bị.")

    fields = body.model_dump(exclude_unset=True)
    if "zone_id" in fields and fields["zone_id"] is not None:
        if not db.query(ZoneModel).filter(ZoneModel.id == fields["zone_id"]).first():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Khu vực không tồn tại.")
    # null tường minh = bỏ loại, client quay về suy từ tên.
    if fields.get("category") is not None and fields["category"] not in DEVICE_CATEGORIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Loại không hợp lệ. Hợp lệ: {list(DEVICE_CATEGORIES)}"
        )

    for key, value in fields.items():
        setattr(device, key, value)
    db.commit()
    db.refresh(device)

    zone = None
    if device.zone_id is not None:
        zone = db.query(ZoneModel).filter(ZoneModel.id == device.zone_id).first()
    return {"status": "success", "data": _device_to_dict(device, zone)}


@app.delete("/api/devices/{device_id}")
async def delete_device(
    device_id: str,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(require_owner),
):
    # Dùng Depends(get_db) để session luôn được đóng (kể cả khi lỗi) — tránh leak.
    try:
        device = db.query(DeviceModel).filter(DeviceModel.id == device_id).first()
        if not device:
            return {"status": "error", "message": "Không tìm thấy thiết bị để xóa."}

        # Xóa luôn lịch của thiết bị. Không làm thì lịch mồ côi vẫn được
        # scheduler bắn vào một thiết bị không còn tồn tại, mỗi ngày, mãi mãi.
        orphans = db.query(ScheduleModel).filter(ScheduleModel.device_id == device_id).count()
        if orphans:
            db.query(ScheduleModel).filter(ScheduleModel.device_id == device_id).delete()

        db.delete(device)
        db.commit()
        logger.info(f"Đã xóa thiết bị {device_id} (kèm {orphans} lịch hẹn)")
        return {
            "status": "success",
            "message": f"Đã xóa thiết bị {device_id}"
            + (f" và {orphans} lịch hẹn của nó" if orphans else ""),
        }
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

def _log_control(db: Session, device: DeviceModel, action_type: str, action_value: str | None,
                 via: str, member: MemberModel, ok: bool, error: str | None = None) -> None:
    """Ghi lịch sử cho endpoint control. `via` do app tự khai — chỉ nhận giá trị
    trong CLIENT_SOURCES, lạ thì coi là "app" (client không giả được nguồn khác)."""
    source = via if via in command_log.CLIENT_SOURCES else "app"
    command_log.record(db, device=device, action_type=action_type, action_value=action_value,
                       source=source, success=ok, member=member, detail=error)

# =========================================================
# API - Test Control Device (Action & Mode)
# =========================================================
@app.get("/api/test-control/{brand}/{device_id}")
async def test_control(
    brand: str,
    device_id: str,
    action: str = "on",
    via: str = "app",
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    # Hãng lấy từ DB, không tin URL: sai hãng = gửi id tới nhầm connector + lệch key cache.
    device = require_device_access(db, member, device_id)
    brand = device.brand
    # Trước đây mọi giá trị khác "on" (gõ sai, "open", "toggle"...) đều thành
    # turn_off — với cửa cuốn là ĐÓNG CỬA.
    if action not in ("on", "off"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action phải là on hoặc off")
    try:
        connector = device_manager.get_connector(brand)
        if action == "on":
            ok = await connector.turn_on(device_id)
        else:
            ok = await connector.turn_off(device_id)
        _cache_invalidate(brand, device_id)
        _log_control(db, device, action, None, via, member, ok)
        if not ok:
            logger.warning(f"Lệnh {action} cho {device_id} qua {brand} không thành công")
            return {"status": "error", "message": f"Thiết bị {device_id} không nhận lệnh {action}"}
        logger.info(f"Đã thực hiện lệnh {action} cho thiết bị {device_id} qua {brand}")
        return {"status": "success", "message": f"Đã {action} thiết bị {device_id} ({brand})"}
    except Exception as e:
        logger.error(f"Lỗi điều khiển {brand}: {e}")
        _log_control(db, device, action, None, via, member, False, str(e))
        return {"status": "error", "message": str(e)}

@app.get("/api/test-control/{brand}/{device_id}/mode")
async def test_control_mode(
    brand: str,
    device_id: str,
    mode: str,
    via: str = "app",
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    # Hãng lấy từ DB, không tin URL: sai hãng = gửi id tới nhầm connector + lệch key cache.
    device = require_device_access(db, member, device_id)
    brand = device.brand
    try:
        connector = device_manager.get_connector(brand)
        if hasattr(connector, 'set_mode'):
            ok = await connector.set_mode(device_id, mode)
            _cache_invalidate(brand, device_id)
            _log_control(db, device, "mode", mode, via, member, ok)
            if not ok:
                logger.warning(f"Đổi chế độ {mode} cho {device_id} qua {brand} không thành công")
                return {"status": "error", "message": f"Thiết bị không nhận chế độ {mode}"}
            logger.info(f"Đã chuyển chế độ {mode} cho thiết bị {device_id} qua {brand}")
            return {"status": "success", "message": f"Đã chuyển sang chế độ {mode}"}
        else:
            return {"status": "error", "message": "Thiết bị không hỗ trợ đổi chế độ"}
    except Exception as e:
        logger.error(f"Lỗi đổi chế độ {brand}: {e}")
        _log_control(db, device, "mode", mode, via, member, False, str(e))
        return {"status": "error", "message": str(e)}

# =========================================================
# API - Lấy trạng thái THẬT của thiết bị (query từ phần cứng)
# =========================================================
@app.get("/api/devices/{brand}/{device_id}/status")
async def get_device_status(
    brand: str,
    device_id: str,
    fresh: bool = False,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    # Hãng lấy từ DB, không tin URL: sai hãng = gửi id tới nhầm connector + lệch key cache.
    device = require_device_access(db, member, device_id)
    brand = device.brand
    try:
        # fresh=1: bỏ qua cache (client gọi ngay sau lệnh điều khiển để lấy
        # trạng thái mới nhất). Poll định kỳ vẫn dùng cache bình thường.
        if not fresh:
            cached = _cache_get(brand, device_id)
            if cached is not None:
                return {"status": "success", "data": cached, "cached": True}
        connector = device_manager.get_connector(brand)
        state = await connector.get_device_state(device_id)
        _cache_set(brand, device_id, state)
        if isinstance(state, dict):
            device_history.observe_state(db, device, state)
        return {"status": "success", "data": state}
    except Exception as e:
        logger.error(f"Lỗi lấy trạng thái {brand}/{device_id}: {e}")
        return {"status": "error", "message": str(e)}

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

async def _execute_device_action(device: DeviceModel | None, verb: str | None, mode: str | None,
                                 requested_id: str | None = None, *, db: Session | None = None,
                                 member: MemberModel | None = None, source: str = "voice",
                                 detail: str | None = None) -> dict:
    """
    Thi hành 1 hành động "không qua UI" (trợ lý AI, kịch bản) trên `device`.
    `device` PHẢI lấy từ danh sách đã lọc theo quyền (device_query) — None nghĩa
    là thiết bị không tồn tại hoặc ngoài khu của người gọi. Hãng lấy từ hàng DB,
    không bao giờ từ dữ liệu AI trả về. Trả bubble {"device_name","action","success"}.
    """
    if device is None:
        return {"device_name": requested_id or "?", "action": "Không có quyền hoặc không tìm thấy thiết bị",
                "success": False}
    try:
        action_type, action_value = normalize_action(device, verb, mode)
    except ValueError as e:
        return {"device_name": device.name, "action": str(e), "success": False}

    success = False
    try:
        success = await execute_schedule_action(
            device.brand, device.id, action_type, action_value, invalidate_cache=_cache_invalidate,
        )
    except Exception as e:
        logger.error(f"[Action Error] {device.brand}/{device.id}: {e}")
    if db is not None:
        command_log.record(db, device=device, action_type=action_type, action_value=action_value,
                           source=source, success=success, member=member, detail=detail)
    return {"device_name": device.name, "action": _action_label_vn(action_type, action_value),
            "success": success}

def _create_schedule_from_intent(action: dict, devices_by_id: dict, db: Session,
                                 member: MemberModel) -> dict:
    """
    Tạo lịch hẹn từ intent 'schedule' của local parser / AI.
    Trả về bubble chat {"device_name","action","success"} — KHÔNG chạm connector.
    Cùng luật quyền với POST /api/schedules: guest không tạo lịch, và chỉ thiết
    bị trong khu được cấp.
    """
    dev_id = action.get("id")
    device_obj = devices_by_id.get(dev_id)
    dev_name = device_obj.name if device_obj else (dev_id or "?")
    try:
        require_can_schedule(member)
    except HTTPException as e:
        return {"device_name": dev_name, "action": f"Lỗi hẹn giờ: {e.detail}", "success": False}
    if device_obj is None:
        return {"device_name": dev_name, "action": "Lỗi hẹn giờ: không có quyền hoặc không tìm thấy thiết bị",
                "success": False}
    try:
        action_type, action_value = normalize_action(device_obj, action.get("action"), action.get("mode"))
        end_time = action.get("end_time")
        end_action_type = end_action_value = None
        if end_time:
            try:
                end_action_type, end_action_value = normalize_action(
                    device_obj, action.get("end_action"), action.get("end_mode"))
            except ValueError:
                end_time = None  # khoảng không có hành động kết thúc hợp lệ -> lịch đơn

        days, one_shot, rolled = resolve_target_days(
            action.get("time", ""), int(action.get("day_offset", 0) or 0),
            bool(action.get("recurring_daily", False)), datetime.now(TZ),
        )
        sch = _create_schedule_row(
            db, name="Tạo bởi trợ lý", brand=device_obj.brand, device_id=device_obj.id,
            action_type=action_type, action_value=action_value,
            time=action.get("time", ""), days=days,
            end_time=end_time, end_action_type=end_action_type,
            end_action_value=end_action_value, one_shot=one_shot,
            created_by=member.user_id,
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
async def parse_voice_command(
    command: VoiceCommand,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    # Depends(get_db): session tự đóng kể cả khi query lỗi — tránh leak.
    # device_query: scoping theo khu là TỰ ĐỘNG — parser chỉ nhìn thấy thiết bị
    # member được phép dùng, nên "bật đèn" của kid không chạm được khu khác.
    # Thứ tự cố định: parser chọn "thiết bị đầu tiên của loại X" phải tất định.
    devices = device_query(db, member).order_by(DeviceModel.id).all()

    text_lower = command.text.lower()
    logger.info(f"Nhận lệnh giọng nói: '{command.text}'")
    actions = []

    # ---------------------------------------------------------
    # KỊCH BẢN: "ra khỏi nhà", "chạy kịch bản đi ngủ"... — xét TRƯỚC tường lửa
    # từ khóa thiết bị (tên kịch bản thường không chứa tên thiết bị nào).
    # ---------------------------------------------------------
    scene = match_scene(text_lower, db.query(SceneModel).all())
    if scene is not None:
        devices_by_id = {d.id: d for d in devices}
        opens_door = any(
            a.get("action_value") == "open" and a.get("device_id") in devices_by_id
            and device_kind(devices_by_id[a["device_id"]]) == "curtain"
            for a in json.loads(scene.actions or "[]")
        )
        # Nhận dạng giọng nói nghe nhầm là có: kịch bản MỞ CỬA chỉ chạy từ màn
        # hình (có hộp xác nhận), không chạy bằng giọng nói.
        if opens_door:
            return {"status": "success", "ai_understood": [], "execution_results": [{
                "device_name": scene.name, "success": False,
                "action": "Kịch bản này mở cửa — hãy chạy trên màn hình chính để xác nhận",
            }]}
        data = await _run_scene(db, member, scene)
        results = data["results"] + ([{
            "device_name": scene.name, "success": False,
            "action": f"Bỏ qua {data['skipped']} thiết bị ngoài khu của bạn",
        }] if data["skipped"] else [])
        return {"status": "success", "ai_understood": [{"intent": "scene", "id": scene.id}],
                "execution_results": results}
    
    # ---------------------------------------------------------
    # BỨC TƯỜNG LỬA: KIỂM TRA TỪ KHÓA THIẾT BỊ
    # ---------------------------------------------------------
    # Danh sách các từ khóa liên quan đến thiết bị trong nhà
    device_keywords = ["quạt", "lọc", "không khí", "mèo", "ăn", "hạt", "cửa", "cuốn", "đèn", "tất cả",
                       "bơm", "tăng áp", "hết", "toàn bộ",
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
    # Chỉ thiết bị trong `devices` (đã lọc theo khu) mới được chạm. id do AI trả
    # về KHÔNG được tin: kid có thể ép câu sang nhánh AI rồi đọc id khu khác.
    devices_by_id = {d.id: d for d in devices}

    async def execute_single_action(action):
        # Ý ĐỊNH HẸN GIỜ: tạo lịch trong DB, TUYỆT ĐỐI không gọi connector.
        if action.get("intent") == "schedule":
            return _create_schedule_from_intent(action, devices_by_id, db, member)

        return await _execute_device_action(
            devices_by_id.get(action.get("id")), action.get("action"), action.get("mode"),
            requested_id=action.get("id"),
            db=db, member=member, source="voice", detail=f"“{command.text}”",
        )

    # Bắn TẤT CẢ các lệnh IoT cùng một lúc (Tốc độ x2, x3)
    # Nếu câu nói có 3 thiết bị, nó sẽ chạy song song cả 3.
    # AI có thể trả object/null thay vì list -> bỏ qua thay vì 500.
    actions = [a for a in actions if isinstance(a, dict)] if isinstance(actions, list) else []
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

def _create_schedule_row(db: Session, *, name: str, brand: str, device_id: str,
                         action_type: str, action_value: str | None, time: str,
                         days: str = "", enabled: bool = True,
                         end_time: str | None = None, end_action_type: str | None = None,
                         end_action_value: str | None = None,
                         one_shot: bool = False,
                         created_by: str | None = None) -> ScheduleModel:
    """Validate + tạo 1 lịch. Dùng chung cho POST /api/schedules và trợ lý AI.
    Lỗi validate -> raise ValueError(thông báo tiếng Việt)."""
    err = _validate_schedule_fields(action_type, action_value, time, days,
                                    end_time, end_action_type, end_action_value)
    if err:
        raise ValueError(err)
    sch = ScheduleModel(
        name=name, brand=brand, device_id=device_id,
        action_type=action_type, action_value=action_value,
        time=time, days=days, enabled=enabled,
        end_time=end_time, end_action_type=end_action_type,
        end_action_value=end_action_value, one_shot=one_shot,
        created_by=created_by,
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
        "created_by": s.created_by,
    }

@app.get("/api/schedules")
async def list_schedules(
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    # Lọc theo THIẾT BỊ, không theo người tạo: lịch là của cả nhà, ai thấy
    # thiết bị thì thấy lịch của nó.
    schedules = schedule_query(db, member).order_by(ScheduleModel.time).all()
    return {"status": "success", "data": [_schedule_to_dict(s) for s in schedules]}

@app.post("/api/schedules")
async def create_schedule(
    body: ScheduleCreate,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    require_can_schedule(member)
    require_device_access(db, member, body.device_id)
    try:
        sch = _create_schedule_row(
            db, name=body.name, brand=body.brand, device_id=body.device_id,
            action_type=body.action_type, action_value=body.action_value,
            time=body.time, days=body.days, enabled=body.enabled,
            end_time=body.end_time, end_action_type=body.end_action_type,
            end_action_value=body.end_action_value, one_shot=body.one_shot,
            created_by=member.user_id,
        )
        return {"status": "success", "data": _schedule_to_dict(sch)}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi tạo lịch: {e}")
        return {"status": "error", "message": str(e)}

@app.patch("/api/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    sch = require_schedule_write(db, member, schedule_id)
    fields = body.model_dump(exclude_unset=True)
    # Chuyển lịch sang thiết bị khác: phải có quyền với thiết bị MỚI (không thì
    # kid trỏ lịch của mình sang khu khác), và hãng lấy từ DB chứ không từ body.
    if fields.get("device_id") and fields["device_id"] != sch.device_id:
        fields["brand"] = require_device_access(db, member, fields["device_id"]).brand
    else:
        fields.pop("device_id", None)
        fields.pop("brand", None)
    # App gửi lại đủ form khi sửa (kể cả đổi tên) -> chỉ coi là "đổi giờ" khi
    # giá trị THỰC SỰ khác; nếu không, đổi tên ngay sau khi lịch vừa chạy sẽ
    # xóa last_fired_date và lịch chạy LẦN NỮA trong cửa sổ 120s.
    time_changed = "time" in fields and fields["time"] != sch.time
    end_changed = "end_time" in fields and fields["end_time"] != sch.end_time
    re_enabled = fields.get("enabled") is True and not sch.enabled
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
        if time_changed or re_enabled:
            sch.last_fired_date = None
        if end_changed or re_enabled:
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
async def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    sch = require_schedule_write(db, member, schedule_id)
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
async def run_schedule_now(
    schedule_id: int,
    part: str = "start",
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    """Chạy NGAY hành động của lịch (để test), không ảnh hưởng last_fired_date.
    part=end: chạy hành động KẾT THÚC của lịch khoảng."""
    # Chạy tay = điều khiển thiết bị, nên chỉ cần quyền dùng thiết bị đó,
    # không cần quyền sửa lịch (kid bấm chạy thử lịch bố mẹ đặt là hợp lý).
    sch = schedule_query(db, member).filter(ScheduleModel.id == schedule_id).first()
    if not sch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy lịch.")
    if part == "end" and not sch.end_time:
        return {"status": "error", "message": "Lịch này không có hành động kết thúc."}
    action_type = sch.end_action_type if part == "end" else sch.action_type
    action_value = sch.end_action_value if part == "end" else sch.action_value
    device = db.query(DeviceModel).filter(DeviceModel.id == sch.device_id).first()
    label = f"Chạy thử lịch “{sch.name or sch.time}”" + (" (kết thúc)" if part == "end" else "")
    try:
        ok = await execute_schedule_action(
            sch.brand, sch.device_id, action_type, action_value,
            invalidate_cache=_cache_invalidate,
        )
        command_log.record(db, device=device, device_id=sch.device_id, action_type=action_type,
                           action_value=action_value, source="schedule", success=ok,
                           member=member, detail=label)
        if not ok:
            return {"status": "error", "message": "Thiết bị không nhận lệnh."}
        return {"status": "success", "message": f"Đã chạy lịch #{schedule_id}"}
    except Exception as e:
        logger.error(f"Lỗi chạy lịch #{schedule_id}: {e}")
        command_log.record(db, device=device, device_id=sch.device_id, action_type=action_type,
                           action_value=action_value, source="schedule", success=False,
                           member=member, detail=f"{label}: {e}")
        return {"status": "error", "message": str(e)}

# =========================================================
# API - Kịch bản (1 nút chạy nhiều hành động)
# =========================================================
_MAX_SCENE_ACTIONS = 20


class SceneAction(BaseModel):
    device_id: str
    action_type: str                  # on | off | mode
    action_value: str | None = None


class SceneBody(BaseModel):
    name: str
    icon: str | None = None
    sort_order: int = 0
    actions: list[SceneAction] = []


class SceneUpdate(BaseModel):
    name: str | None = None
    icon: str | None = None
    sort_order: int | None = None
    actions: list[SceneAction] | None = None


def _scene_to_dict(s: SceneModel) -> dict:
    return {
        "id": s.id, "name": s.name, "icon": s.icon, "sort_order": s.sort_order,
        "actions": json.loads(s.actions or "[]"), "created_by": s.created_by,
    }


def _normalize_scene_actions(db: Session, member: MemberModel, actions: list[SceneAction]) -> str:
    """Kiểm từng hành động (thiết bị tồn tại + mình dùng được + hợp lệ với loại) -> JSON đã chuẩn hóa."""
    if not actions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kịch bản cần ít nhất 1 hành động.")
    if len(actions) > _MAX_SCENE_ACTIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Tối đa {_MAX_SCENE_ACTIONS} hành động.")
    out = []
    for a in actions:
        device = require_device_access(db, member, a.device_id)
        try:
            action_type, action_value = normalize_action(device, a.action_type, a.action_value)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{device.name}: {e}")
        out.append({"device_id": device.id, "action_type": action_type, "action_value": action_value})
    return json.dumps(out, ensure_ascii=False)


def _clean_scene_name(name: str | None) -> str:
    name = (name or "").strip()
    if not 1 <= len(name) <= 40:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tên kịch bản phải từ 1 đến 40 ký tự.")
    return name


@app.get("/api/scenes")
async def list_scenes(
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    # Kịch bản là của cả nhà: ai cũng thấy; chạy thì chỉ phần mình dùng được.
    scenes = db.query(SceneModel).order_by(SceneModel.sort_order, SceneModel.id).all()
    return {"status": "success", "data": [_scene_to_dict(s) for s in scenes]}


@app.post("/api/scenes")
async def create_scene(
    body: SceneBody,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    require_scene_write(member)
    scene = SceneModel(
        name=_clean_scene_name(body.name), icon=body.icon, sort_order=body.sort_order,
        actions=_normalize_scene_actions(db, member, body.actions), created_by=member.user_id,
    )
    db.add(scene)
    db.commit()
    db.refresh(scene)
    logger.info(f"🎬 Đã tạo kịch bản #{scene.id}: {scene.name}")
    return {"status": "success", "data": _scene_to_dict(scene)}


def _get_scene(db: Session, scene_id: int) -> SceneModel:
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()
    if scene is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy kịch bản.")
    return scene


@app.patch("/api/scenes/{scene_id}")
async def update_scene(
    scene_id: int,
    body: SceneUpdate,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    require_scene_write(member)
    scene = _get_scene(db, scene_id)
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields:
        scene.name = _clean_scene_name(fields["name"])
    if "icon" in fields:
        scene.icon = fields["icon"]
    if fields.get("sort_order") is not None:
        scene.sort_order = fields["sort_order"]
    if body.actions is not None:
        scene.actions = _normalize_scene_actions(db, member, body.actions)
    db.commit()
    db.refresh(scene)
    return {"status": "success", "data": _scene_to_dict(scene)}


@app.delete("/api/scenes/{scene_id}")
async def delete_scene(
    scene_id: int,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    require_scene_write(member)
    db.delete(_get_scene(db, scene_id))
    db.commit()
    return {"status": "success", "message": f"Đã xóa kịch bản #{scene_id}"}


async def _run_scene(db: Session, member: MemberModel, scene: SceneModel) -> dict:
    """
    Chạy kịch bản TUẦN TỰ (không song song: 2 lệnh cùng connector Tuya chen nhau
    thì interlock stop->open của cửa có thể lẫn với lệnh khác). Hành động trên
    thiết bị ngoài khu của người chạy bị BỎ QUA và báo lại, không chạy thay.
    """
    devices_by_id = {d.id: d for d in device_query(db, member).all()}
    results, skipped = [], 0
    for a in json.loads(scene.actions or "[]"):
        device = devices_by_id.get(a.get("device_id"))
        if device is None:
            skipped += 1
            continue
        results.append(await _execute_device_action(
            device, a.get("action_type"), a.get("action_value"),
            db=db, member=member, source="scene", detail=f"Kịch bản “{scene.name}”",
        ))
    return {"scene": scene.name, "results": results, "skipped": skipped}


@app.post("/api/scenes/{scene_id}/run")
async def run_scene(
    scene_id: int,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    data = await _run_scene(db, member, _get_scene(db, scene_id))
    logger.info(f"🎬 {member.user_id} chạy kịch bản #{scene_id}: "
                f"{sum(r['success'] for r in data['results'])}/{len(data['results'])} ok, bỏ qua {data['skipped']}")
    return {"status": "success", "data": data}


# =========================================================
# API - Lịch sử lệnh điều khiển (ai / từ đâu / lúc nào)
# =========================================================
_HISTORY_SYNC_TIMEOUT = 10.0  # đọc nhật ký Tuya chậm thì trả dữ liệu đang có, lần sau bù


def _log_to_dict(r: CommandLogModel) -> dict:
    return {
        "id": r.id, "at_ms": r.at_ms, "device_id": r.device_id, "device_name": r.device_name,
        "action_label": r.action_label, "source": r.source, "user_name": r.user_name,
        "success": r.success, "detail": r.detail,
    }


@app.get("/api/history")
async def list_history(
    limit: int = 50,
    before_ms: int | None = None,
    device_id: str | None = None,
    sync: bool = True,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    """
    Lịch sử mới nhất trước, phân trang bằng `before_ms`. Chỉ thiết bị người gọi
    THẤY được (cùng luật device_query với /api/devices) — lịch sử là của cả nhà,
    không lọc theo người bấm. `sync=1` (mặc định) kéo nhật ký Tuya mới (nút vật
    lý, app Smart Life) trước khi trả; mỗi thiết bị tối đa 1 lần/60s.
    """
    devices = device_query(db, member).all()
    if device_id is not None:
        devices = [require_device_access(db, member, device_id)]
    if sync:
        try:
            await asyncio.wait_for(device_history.sync_external_events(db, devices), _HISTORY_SYNC_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Đồng bộ nhật ký thiết bị quá lâu — trả lịch sử đang có.")
        except Exception as e:
            logger.warning(f"Đồng bộ nhật ký thiết bị lỗi: {e}")
            db.rollback()

    limit = max(1, min(limit, 200))
    q = db.query(CommandLogModel).filter(CommandLogModel.device_id.in_([d.id for d in devices]))
    if before_ms is not None:
        q = q.filter(CommandLogModel.at_ms < before_ms)
    rows = q.order_by(CommandLogModel.at_ms.desc(), CommandLogModel.id.desc()).limit(limit).all()
    return {"status": "success", "data": [_log_to_dict(r) for r in rows], "has_more": len(rows) == limit}


# =========================================================
# API - Tôi là ai (app gọi ngay sau đăng nhập để biết vào màn hình nào)
# =========================================================
@app.get("/api/me")
async def whoami(
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_member),
):
    """
    Dùng get_member (KHÔNG chặn pending) — app phải đọc được trạng thái của
    chính mình để biết hiện màn hình chờ duyệt hay màn hình chính.
    """
    zones = [_zone_to_dict(z) for z in accessible_zones(db, member)]
    return {
        "status": "success",
        "data": {
            **member_to_dict(member, zone_ids_of(db, member.user_id)),
            "zones": zones,
        },
    }


@app.patch("/api/me")
async def update_me(
    body: MeUpdate,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_member),
):
    """
    Sửa hồ sơ của chính mình. Dùng get_member (cho cả pending) để người mới đặt
    được tên thật — chủ nhà nhận ra ai đang chờ duyệt. Người bị chặn thì không.
    Không có trường vai/trạng thái: quyền chỉ đổi qua PATCH /api/members (chủ nhà).
    """
    if member.status == "blocked":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tài khoản đã bị chặn.")
    fields = body.model_dump(exclude_unset=True)
    if "display_name" in fields:
        name = (fields["display_name"] or "").strip()
        if not 1 <= len(name) <= 40:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tên hiển thị phải từ 1 đến 40 ký tự.")
        member.display_name = name
    if "avatar_color" in fields:
        color = fields["avatar_color"]
        if color is not None and not _re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Màu phải có dạng #RRGGBB.")
        member.avatar_color = color
    db.commit()
    db.refresh(member)
    return {"status": "success", "data": member_to_dict(member, zone_ids_of(db, member.user_id))}


@app.post("/api/auth/app-token")
async def create_app_token(
    member: MemberModel = Depends(get_current_member),
):
    """
    Cấp token dài hạn cho app lưu vào SharedPreferences.

    Dùng cho isolate nền của Android (Home Widget, shortcut đã pin) — nơi
    Supabase chưa được khởi tạo nên không lấy được access token. Xem
    `core/auth.py::issue_app_token` để biết vì sao không dùng cách khác.
    """
    token = issue_app_token(member.user_id, member.email)
    return {"status": "success", "data": {"app_token": token}}


# =========================================================
# API - Khu vực (chỉ chủ nhà sửa; ai cũng đọc được khu của mình)
# =========================================================
@app.get("/api/zones")
async def list_zones(
    db: Session = Depends(get_db),
    member: MemberModel = Depends(get_current_member),
):
    zones = accessible_zones(db, member)
    return {"status": "success", "data": [_zone_to_dict(z) for z in zones]}


@app.post("/api/zones")
async def create_zone(
    body: ZoneCreate,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(require_owner),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tên khu vực không được để trống.")
    zone = ZoneModel(name=name, sort_order=body.sort_order, is_shared=body.is_shared)
    db.add(zone)
    db.commit()
    db.refresh(zone)
    logger.info(f"Đã tạo khu vực #{zone.id}: {zone.name}")
    return {"status": "success", "data": _zone_to_dict(zone)}


@app.patch("/api/zones/{zone_id}")
async def update_zone(
    zone_id: int,
    body: ZoneUpdate,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(require_owner),
):
    zone = db.query(ZoneModel).filter(ZoneModel.id == zone_id).first()
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy khu vực.")
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields:
        if not (fields["name"] or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tên khu vực không được để trống.")
        fields["name"] = fields["name"].strip()
    for key, value in fields.items():
        setattr(zone, key, value)
    db.commit()
    db.refresh(zone)
    return {"status": "success", "data": _zone_to_dict(zone)}


@app.delete("/api/zones/{zone_id}")
async def delete_zone(
    zone_id: int,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(require_owner),
):
    zone = db.query(ZoneModel).filter(ZoneModel.id == zone_id).first()
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy khu vực.")

    # Thiết bị KHÔNG bị xóa theo — chúng về "hộp thư đến" (zone_id NULL) để chủ
    # nhà gán lại. Xóa thiết bị theo khu là mất luôn cả lịch hẹn của chúng.
    moved = db.query(DeviceModel).filter(DeviceModel.zone_id == zone_id).count()
    db.query(DeviceModel).filter(DeviceModel.zone_id == zone_id).update({"zone_id": None})
    db.query(MemberZoneAccessModel).filter(MemberZoneAccessModel.zone_id == zone_id).delete()
    db.delete(zone)
    db.commit()
    logger.info(f"Đã xóa khu vực #{zone_id}; {moved} thiết bị về hộp thư đến")
    message = "Đã xóa khu vực"
    if moved:
        message += f"; {moved} thiết bị chuyển về mục chưa phân khu"
    return {"status": "success", "message": message}


# =========================================================
# API - Thành viên (chỉ chủ nhà)
# =========================================================
@app.get("/api/members")
async def list_members(
    db: Session = Depends(get_db),
    member: MemberModel = Depends(require_owner),
):
    rows = db.query(MemberModel).order_by(MemberModel.status, MemberModel.email).all()
    return {
        "status": "success",
        "data": [member_to_dict(m, zone_ids_of(db, m.user_id)) for m in rows],
    }


@app.patch("/api/members/{user_id}")
async def update_member(
    user_id: str,
    body: MemberUpdate,
    db: Session = Depends(get_db),
    member: MemberModel = Depends(require_owner),
):
    """Duyệt / đổi vai / cấp khu. `zone_ids` thay CẢ BỘ grant, không phải add-remove."""
    target = db.query(MemberModel).filter(MemberModel.user_id == user_id).first()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thành viên.")

    fields = body.model_dump(exclude_unset=True)

    if "role" in fields and fields["role"] not in ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Vai không hợp lệ. Hợp lệ: {list(ROLES)}"
        )
    if "status" in fields and fields["status"] not in STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Trạng thái không hợp lệ. Hợp lệ: {list(STATUSES)}"
        )

    # Tự hạ vai / tự chặn mình = tự khóa mình khỏi nhà mình. Chặn ở API chứ không
    # chỉ ở UI: app bản cũ hoặc request gõ tay vẫn đi thẳng vào đây được.
    if target.user_id == member.user_id:
        if fields.get("role", target.role) != "owner":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Không thể tự hạ vai của chính mình."
            )
        if fields.get("status", target.status) != "active":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Không thể tự chặn chính mình.")

    # Backstop cho "nhà mất chủ". Hiện tại KHÔNG chạm tới được: người thao tác
    # bắt buộc là owner/active (require_owner), nên hạ vai một owner khác thì
    # luôn còn ít nhất 2 owner, còn tự hạ vai đã bị chốt phía trên bắt. Giữ lại
    # vì nó rẻ và sẽ thành đường chạy thật nếu sau này nới chốt tự-hạ-vai.
    losing_owner = target.role == "owner" and (
        fields.get("role", "owner") != "owner" or fields.get("status", "active") != "active"
    )
    if losing_owner:
        remaining = (
            db.query(MemberModel)
            .filter(
                MemberModel.role == "owner",
                MemberModel.status == "active",
                MemberModel.user_id != target.user_id,
            )
            .count()
        )
        if remaining == 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Đây là chủ nhà duy nhất — hãy chỉ định chủ nhà khác trước.",
            )

    zone_ids = fields.pop("zone_ids", None)
    for key, value in fields.items():
        setattr(target, key, value)

    if zone_ids is not None:
        valid = {z.id for z in db.query(ZoneModel).filter(ZoneModel.id.in_(zone_ids)).all()}
        unknown = set(zone_ids) - valid
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Khu vực không tồn tại: {sorted(unknown)}"
            )
        db.query(MemberZoneAccessModel).filter(
            MemberZoneAccessModel.user_id == user_id
        ).delete()
        for zid in valid:
            db.add(MemberZoneAccessModel(user_id=user_id, zone_id=zid))

    db.commit()
    db.refresh(target)
    logger.info(
        f"Đã cập nhật thành viên {target.email}: vai={target.role} trạng thái={target.status}"
    )
    return {"status": "success", "data": member_to_dict(target, zone_ids_of(db, user_id))}


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

    LUÔN trả 200 để UptimeRobot không báo động đỏ mỗi lần DB chớp; trạng thái
    DB nằm trong body (`db: false` = app sống nhưng DB chưa khởi tạo được).
    """
    return {"status": "online", "db": db_ready}

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