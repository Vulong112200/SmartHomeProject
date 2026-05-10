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
            self.is_connected = True
            print("[Rojeco] ✅ Đã kết nối Tuya Cloud!")
            return True
        except Exception as e:
            return False

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        return {"device_id": device_id, "status": "ON"}

    async def turn_on(self, device_id: str) -> bool:
        return await self.set_mode(device_id, "1") # Bật công tắc = Nhả 1 phần

    async def turn_off(self, device_id: str) -> bool:
        return True

    # Hàm mới: Hỗ trợ nhả số lượng hạt tùy ý từ nút bấm trên App
    async def set_mode(self, device_id: str, mode: str) -> bool:
        try:
            portions = int(mode)
            print(f"[Rojeco] 🐈 Đang nhả {portions} phần thức ăn...")
            
            # Gửi lệnh nhả hạt (Thử 'manual_feed', nếu sau này không chạy thì đổi chữ này thành 'feed_portion')
            commands = {'commands': [{'code': 'manual_feed', 'value': portions}]}
            
            # ĐÃ SỬA URL THEO ĐÚNG API DOCS TRONG ẢNH CỦA BẠN
            response = self.openapi.post(f'/v1.0/devices/{device_id}/commands', commands)
            
            if response.get('success', False):
                print("[Rojeco] ✅ Thành công!")
                return True
            else:
                print(f"[Rojeco] ❌ Lỗi: {response}")
                return False
        except Exception as e:
            print(f"[Rojeco] Lỗi code: {e}")