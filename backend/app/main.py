# backend/app/main.py

import sys
import os
import asyncio
from datetime import datetime

from fastapi import FastAPI, WebSocket, Depends
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session

from app.services.connector_manager import device_manager
from app.services.tuya_connector import TuyaConnector
from app.services.vesync_connector import VeSyncConnector
from app.services.rojeco_connector import RojecoConnector

from app.services.ai_parser import ai_parser
from app.services.automation_engine import (
    automation_engine,
    AutomationRule
)

from app.core.database import engine, Base, get_db
from app.models.device import DeviceModel


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

print("Tạo Database...")
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

    print("Khởi động các connector...")

    # =========================
    # Tuya
    # =========================

    tuya_plugin = TuyaConnector(
        api_key="tuya_key_123",
        api_secret="tuya_secret_456"
    )

    await tuya_plugin.connect()

    device_manager.register_connector(
        "tuya",
        tuya_plugin
    )

    # =========================
    # VeSync
    # =========================

    vesync_plugin = VeSyncConnector(
        email="haphivuboris@gmail.com",
        password="Hoalong741369@"
    )

    await vesync_plugin.connect()

    device_manager.register_connector(
        "vesync",
        vesync_plugin
    )

    # =========================
    # Rojeco
    # =========================

    rojeco_plugin = RojecoConnector()

    await rojeco_plugin.connect()

    device_manager.register_connector(
        "rojeco",
        rojeco_plugin
    )

    # =====================================================
    # Automation Rules
    # =====================================================

    # ---------- IF ----------

    def is_second_0():
        return datetime.now().second == 0

    def is_second_30():
        return datetime.now().second == 30

    # ---------- THEN ----------

    async def auto_turn_on():
        connector = device_manager.get_connector("tuya")
        await connector.turn_on("den_phong_khach")

    async def auto_turn_off():
        connector = device_manager.get_connector("tuya")
        await connector.turn_off("den_phong_khach")

    # ---------- RULES ----------

    rule1 = AutomationRule(
        name="Bật đèn vào đầu phút",
        condition=is_second_0,
        action=auto_turn_on
    )

    rule2 = AutomationRule(
        name="Tắt đèn vào giữa phút",
        condition=is_second_30,
        action=auto_turn_off
    )

    automation_engine.add_rule(rule1)
    automation_engine.add_rule(rule2)

    # Chạy automation engine background

    asyncio.create_task(
        automation_engine.start_engine()
    )


# =========================================================
# API - Get Devices
# =========================================================

@app.get("/api/devices")
async def get_all_devices(
    db: Session = Depends(get_db)
):
    """
    Lấy danh sách toàn bộ thiết bị
    được lưu trong Database
    """

    devices = db.query(DeviceModel).all()

    return {
        "status": "success",
        "data": devices
    }


# =========================================================
# API - Add Device
# =========================================================

@app.post("/api/devices")
async def add_device(
    id: str,
    name: str,
    brand: str,
    db: Session = Depends(get_db)
):
    """
    Thêm thiết bị mới vào Database
    """

    try:

        new_device = DeviceModel(
            id=id,
            name=name,
            brand=brand,
            is_active=True
        )

        db.add(new_device)

        db.commit()

        db.refresh(new_device)

        return {
            "status": "success",
            "message": f"Đã thêm thiết bị: {name}"
        }

    except Exception as e:

        db.rollback()

        return {
            "status": "error",
            "message": f"Không thể thêm thiết bị: {str(e)}"
        }


# =========================================================
# Root
# =========================================================

@app.get("/")
async def root():
    return {
        "message": "Hệ thống Smart Home Backend đang hoạt động!"
    }


# =========================================================
# Favicon
# =========================================================

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(
        content="",
        media_type="image/x-icon"
    )


# =========================================================
# API - Test Control Device
# =========================================================

@app.get("/api/test-control/{brand}/{device_id}")
async def test_control(
    brand: str,
    device_id: str,
    action: str = "on"
):

    try:

        connector = device_manager.get_connector(brand)

        if action == "on":
            await connector.turn_on(device_id)
        else:
            await connector.turn_off(device_id)

        return {
            "status": "success",
            "message":
                f"Đã thực hiện lệnh {action} "
                f"cho thiết bị {device_id} qua {brand}"
        }

    except Exception as e:

        return {
            "status": "error",
            "message": str(e)
        }


# =========================================================
# WebSocket
# =========================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()

    try:

        while True:

            # Nhận câu lệnh từ app điện thoại
            user_text = await websocket.receive_text()

            # AI phân tích
            parsed_cmd = ai_parser.parse_command(user_text)

            # Thực hiện hành động
            if (
                parsed_cmd["intent"] in ["on", "off"]
                and parsed_cmd["device_id"] != "unknown"
            ):

                try:

                    connector = device_manager.get_connector(
                        parsed_cmd["brand"]
                    )

                    if parsed_cmd["intent"] == "on":
                        await connector.turn_on(
                            parsed_cmd["device_id"]
                        )
                    else:
                        await connector.turn_off(
                            parsed_cmd["device_id"]
                        )

                    response = (
                        f"🤖 AI: "
                        f"Đã {parsed_cmd['intent'].upper()} "
                        f"thiết bị "
                        f"{parsed_cmd['device_id']} "
                        f"({parsed_cmd['brand']})"
                    )

                except ValueError:

                    response = (
                        f"🤖 AI: "
                        f"Chưa cấu hình hệ sinh thái "
                        f"{parsed_cmd['brand']}"
                    )

                except Exception as e:

                    response = f"❌ Lỗi: {str(e)}"

            else:

                response = (
                    f"🤖 AI: "
                    f"Tôi chưa hiểu lệnh '{user_text}'. "
                    f"Bạn thử nói "
                    f"'Bật đèn' hoặc 'Tắt quạt' xem?"
                )

            # Gửi kết quả về app
            await websocket.send_text(response)

    except Exception as e:

        print(f"Kết nối bị ngắt: {e}")
        
@app.get("/api/test-control/{brand}/{device_id}/mode")
async def test_control_mode(brand: str, device_id: str, mode: str):
    try:
        connector = device_manager.get_connector(brand)
        
        # Kiểm tra xem Connector này có hỗ trợ đổi chế độ không
        if hasattr(connector, 'set_mode'):
            await connector.set_mode(device_id, mode)
            return {"status": "success", "message": f"Đã chuyển sang chế độ {mode}"}
        else:
            return {"status": "error", "message": "Thiết bị này không hỗ trợ đổi chế độ"}
    except Exception as e:
        return {"status": "error", "message": str(e)}