from tuya_connector import TuyaOpenAPI
from .base_connector import DeviceConnector
from typing import Dict, Any

class RojecoConnector(DeviceConnector):
    def __init__(self):
        self.is_connected = False
        
        # --- ĐIỀN 2 MÃ CỦA BẠN VÀO ĐÂY ---
        self.ACCESS_ID = "vucjttuxyjnvq9drt4j9"      # Vd: vuqttuxyj...
        self.ACCESS_KEY = "dffb86f14ef34d87a14d38c0f30314ce" # Vd: dffb86f...
        
        # Server cho khu vực Singapore
        self.API_ENDPOINT = "https://openapi.tuyain.com" 
        
        self.openapi = TuyaOpenAPI(self.API_ENDPOINT, self.ACCESS_ID, self.ACCESS_KEY)

    async def connect(self) -> bool:
        try:
            self.openapi.connect()
            print("[Rojeco] ✅ Đã kết nối thành công với Tuya Cloud!")
            self.is_connected = True
            return True
        except Exception as e:
            print(f"[Rojeco] ❌ Lỗi kết nối Tuya: {e}")
            return False

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        return {"device_id": device_id, "status": "ON"}

    async def turn_on(self, device_id: str) -> bool:
        if not self.is_connected: 
            return False
        print(f"[Rojeco] 🐈 Đang ra lệnh nhả 1 phần thức ăn...")
        
        # Lệnh nhả hạt chuẩn của Tuya cho Smart Feeder
        commands = {'commands': [{'code': 'manual_feed', 'value': 1}]}
        response = self.openapi.post(f'/v1.0/iot-03/devices/{device_id}/commands', commands)
        
        if response.get('success', False):
            print("[Rojeco] ✅ Đã nhả thức ăn thành công!")
            return True
        else:
            print(f"[Rojeco] ❌ Lỗi: {response}")
            return False

    async def turn_off(self, device_id: str) -> bool:
        print("[Rojeco] Nút TẮT không có tác dụng với máy cho ăn.")
        return True