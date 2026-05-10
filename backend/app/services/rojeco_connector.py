from tuya_connector import TuyaOpenAPI
from .base_connector import DeviceConnector
from typing import Dict, Any

class RojecoConnector(DeviceConnector):
    def __init__(self):
        self.is_connected = False
        
        # --- ĐIỀN 2 MÃ CỦA BẠN VÀO ĐÂY ---
        self.ACCESS_ID = "vucjttuxyjnvq9drt4j9"      # Vd: vuqttuxyj...
        self.ACCESS_KEY = "dffb86f14ef34d87a14d38c0f30314ce" # Vd: dffb86f...
        
        # Endpoint chuẩn cho Singapore Data Center
        self.API_ENDPOINT = "https://openapi.tuyaus.com" 
        
        self.openapi = TuyaOpenAPI(self.API_ENDPOINT, self.ACCESS_ID, self.ACCESS_KEY)

    async def connect(self) -> bool:
        try:
            result = self.openapi.connect()
            print("[Tuya Token Response]", result)
            self.is_connected = True
            print("[Rojeco] ✅ Đã kết nối Tuya Cloud!")
            return True
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
            if not self.is_connected: self.openapi.connect()
            
            # Chuyển mode sang số nguyên (portions)
            portions = int(mode)
            
            # Cấu trúc Body chuẩn theo ảnh Debug của bạn
            commands = {'commands': [{'code': 'manual_feed', 'value': portions}]}
            
            # ĐƯỜNG DẪN CHUẨN: /v1.0/iot-03/...
            endpoint = f'/v1.0/iot-03/devices/{device_id}/commands'
            response = self.openapi.post(endpoint, commands)
            
            print(f"[Rojeco] Gửi lệnh thành công: {response}")
            return response.get('success', False)
        except Exception as e:
            print(f"[Rojeco] Lỗi: {e}")
            return False