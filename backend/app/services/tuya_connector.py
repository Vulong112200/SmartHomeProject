import asyncio
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
        self.API_ENDPOINT = "https://openapi-sg.iotbing.com/" 
        
        self.openapi = TuyaOpenAPI(self.API_ENDPOINT, self.ACCESS_ID, self.ACCESS_KEY)

    async def connect(self) -> bool:
        try:
            result = self.openapi.connect()
            print("[Tuya Token Response]", result)
            self.is_connected = True
            print("[Tuya] ✅ Đã kết nối Tuya Cloud!")
            return True
        except Exception as e:
            return False

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        """
        Lấy trạng thái thật của cửa cuốn từ Tuya Cloud.
        Endpoint: GET /v1.0/iot-03/devices/{id}/status -> list các DP {code, value}.
        Lưu ý: tên DP tùy thiết bị. In log 1 lần để xác nhận nếu map chưa đúng.
        """
        try:
            if not self.is_connected:
                await asyncio.to_thread(self.openapi.connect)

            endpoint = f'/v1.0/iot-03/devices/{device_id}/status'
            # tuya-connector-python là client đồng bộ (requests) -> chạy trong thread
            # để không block event loop, tránh các request khác xếp hàng nối tiếp.
            response = await asyncio.to_thread(self.openapi.get, endpoint)
            print(f"[Tuya Door] Status raw: {response}")

            if not response.get('success'):
                return {"device_id": device_id, "status": "offline"}

            # Chuyển list DP thành dict cho dễ tra cứu
            dps = {item.get('code'): item.get('value') for item in response.get('result', [])}

            # DP điều khiển gần nhất: 'open' | 'close' | 'stop'
            control = str(dps.get('control', '')).lower()
            # Vị trí hiện tại 0-100 (nếu thiết bị hỗ trợ)
            position = dps.get('percent_state', dps.get('position'))

            # Suy ra trạng thái cửa
            if position is not None:
                try:
                    position = int(position)
                except (TypeError, ValueError):
                    position = None

            if position == 100:
                door_state = "open"
            elif position == 0:
                door_state = "closed"
            elif control == "open":
                door_state = "opening"
            elif control == "close":
                door_state = "closing"
            elif control == "stop":
                door_state = "stopped"
            elif position is not None:
                door_state = "partial"
            else:
                door_state = "unknown"

            return {
                "device_id": device_id,
                "status": "ON" if door_state in ("open", "opening", "partial", "stopped") else "OFF",
                "door_state": door_state,
                "position": position,
            }
        except Exception as e:
            print(f"[Tuya Door] Lỗi đọc trạng thái: {e}")
            return {"device_id": device_id, "status": "offline", "door_state": "unknown"}

    async def turn_on(self, device_id: str) -> bool:
        return await self.set_mode(device_id, "open")

    async def turn_off(self, device_id: str) -> bool:
        return await self.set_mode(device_id, "close")

    async def _send_control(self, device_id: str, value: str):
        """Gửi 1 lệnh 'control' tới Tuya Cloud và trả về response gốc."""
        commands = {'commands': [{'code': 'control', 'value': value}]}
        # ĐƯỜNG DẪN CHUẨN: /v1.0/iot-03/...
        endpoint = f'/v1.0/iot-03/devices/{device_id}/commands'
        # Client đồng bộ -> chạy trong thread để không block event loop.
        response = await asyncio.to_thread(self.openapi.post, endpoint, commands)
        print(f"[Tuya Door] Gửi lệnh {value}: {response}")
        return response

    async def set_mode(self, device_id: str, mode: str) -> bool:
        try:
            if not self.is_connected:
                await asyncio.to_thread(self.openapi.connect)

            # Với cửa cuốn, mode là 'open', 'close', 'stop'
            mode = mode.lower()

            # AN TOÀN INTERLOCK: motor cửa cuốn nếu đang chạy 1 chiều mà nhận
            # lệnh chiều ngược lại có thể xung đột/kẹt. Chèn 1 lệnh 'stop' trước
            # rồi mới gửi 'open'/'close' để lệnh chạy đúng ý người dùng.
            # Không áp dụng khi mode == 'stop' (tránh gửi thừa/đệ quy).
            if mode in ("open", "close"):
                await self._send_control(device_id, "stop")
                await asyncio.sleep(0.4)

            response = await self._send_control(device_id, mode)
            return response.get('success', False)
        except Exception as e:
            print(f"[Tuya Door] Lỗi: {e}")
            return False