import asyncio
import os
from tuya_connector import TuyaOpenAPI
from .base_connector import DeviceConnector
from typing import Dict, Any

class RojecoConnector(DeviceConnector):
    def __init__(self):
        self.is_connected = False
        
        # Credential đọc từ biến môi trường (dùng chung app Tuya với TuyaConnector).
        self.ACCESS_ID = os.getenv("TUYA_ACCESS_ID", "")
        self.ACCESS_KEY = os.getenv("TUYA_ACCESS_KEY", "")

        # Endpoint chuẩn cho Singapore Data Center
        self.API_ENDPOINT = os.getenv("TUYA_API_ENDPOINT", "https://openapi-sg.iotbing.com/")
        
        self.openapi = TuyaOpenAPI(self.API_ENDPOINT, self.ACCESS_ID, self.ACCESS_KEY)

    async def connect(self) -> bool:
        try:
            # Client đồng bộ (requests) -> chạy trong thread, không block event loop.
            result = await asyncio.to_thread(self.openapi.connect)
            print("[Tuya Token Response]", result)
            self.is_connected = bool(result.get("success")) if isinstance(result, dict) else True
            if self.is_connected:
                print("[Rojeco] ✅ Đã kết nối Tuya Cloud!")
            else:
                print(f"[Rojeco] ❌ Tuya từ chối cấp token: {result}")
            return self.is_connected
        except Exception as e:
            print(f"[Rojeco] ❌ Lỗi kết nối mây: {e}")
            return False

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        return {"device_id": device_id, "status": "ON"}

    async def turn_on(self, device_id: str) -> bool:
        return await self.set_mode(device_id, "1")

    async def turn_off(self, device_id: str) -> bool:
        return True

    async def set_mode(self, device_id: str, mode: str) -> bool:
        try:
            if not self.is_connected:
                await asyncio.to_thread(self.openapi.connect)

            # Chuyển mode sang số nguyên (portions)
            portions = int(mode)

            # Cấu trúc Body chuẩn theo ảnh Debug của bạn
            commands = {'commands': [{'code': 'manual_feed', 'value': portions}]}

            # ĐƯỜNG DẪN CHUẨN: /v1.0/iot-03/...
            endpoint = f'/v1.0/iot-03/devices/{device_id}/commands'
            # Client đồng bộ -> chạy trong thread để không block event loop.
            response = await asyncio.to_thread(self.openapi.post, endpoint, commands)
            
            print(f"[Rojeco] Gửi lệnh thành công: {response}")
            return response.get('success', False)
        except Exception as e:
            print(f"[Rojeco] Lỗi: {e}")
            return False