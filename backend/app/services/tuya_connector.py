from tuya_connector import TuyaOpenAPI
from .base_connector import DeviceConnector
from typing import Dict, Any

class TuyaConnector(DeviceConnector):
    def __init__(self):
        self.is_connected = False
        
        # --- ĐIỀN THÔNG TIN TỪ BỨC ẢNH TRƯỚC VÀO ĐÂY ---
        self.ACCESS_ID = "vucjttuxyjnvq9drt4j9"      # Vd: vuqttuxyj...
        self.ACCESS_KEY = "dffb86f14ef34d87a14d38c0f30314ce" # Vd: dffb86f...
        
        # Vì bạn chọn Data Center Singapore, Tuya thường dùng server Ấn Độ (tuyain) hoặc Châu Âu (tuyaeu)
        self.API_ENDPOINT = "https://openapi.tuyain.com" 
        
        self.openapi = TuyaOpenAPI(self.API_ENDPOINT, self.ACCESS_ID, self.ACCESS_KEY)

    async def connect(self) -> bool:
        try:
            self.openapi.connect()
            print("[Tuya] ✅ Đã kết nối thành công với Tuya Cloud!")
            self.is_connected = True
            return True
        except Exception as e:
            print(f"[Tuya] ❌ Lỗi kết nối Tuya: {e}")
            return False

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        return {"device_id": device_id, "status": "ON"}

    async def turn_on(self, device_id: str) -> bool:
        if not self.is_connected: return False
        print(f"[Tuya] 🚪 Đang ra lệnh MỞ thiết bị (Cửa cuốn/Đèn): {device_id}")
        
        # Lệnh mở cửa cuốn của Tuya
        commands = {'commands': [{'code': 'control', 'value': 'open'}]}
        response = self.openapi.post(f'/v1.0/iot-03/devices/{device_id}/commands', commands)
        
        return response.get('success', False)

    async def turn_off(self, device_id: str) -> bool:
        if not self.is_connected: return False
        print(f"[Tuya] 🚪 Đang ra lệnh ĐÓNG thiết bị (Cửa cuốn/Đèn): {device_id}")
        
        # Lệnh đóng cửa cuốn của Tuya
        commands = {'commands': [{'code': 'control', 'value': 'close'}]}
        response = self.openapi.post(f'/v1.0/iot-03/devices/{device_id}/commands', commands)
        
        return response.get('success', False)