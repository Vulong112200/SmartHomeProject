# backend/app/services/vesync_connector.py
import inspect
from pyvesync import VeSync
from .base_connector import DeviceConnector
from typing import Dict, Any

class VeSyncConnector(DeviceConnector):
    def __init__(self, email: str, password: str, time_zone: str = "Asia/Ho_Chi_Minh"):
        self.email = email
        self.password = password
        self.time_zone = time_zone
        self.manager = None
        self.is_connected = False

    async def _safe_call(self, func, *args, **kwargs):
        """
        Hàm hỗ trợ thông minh: Tự động nhận diện thư viện gọi mạng là Sync hay Async.
        Nếu là Async (Coroutine), nó sẽ dùng 'await'. Nếu là Sync, nó trả về bình thường.
        """
        result = func(*args, **kwargs)
        if inspect.iscoroutine(result):
            return await result
        return result

    async def connect(self) -> bool:
        print(f"[VeSync] Đang kết nối với tài khoản: {self.email}...")
        self.manager = VeSync(self.email, self.password, self.time_zone)
        
        # Gọi hàm login qua lớp bọc an toàn
        login_success = await self._safe_call(self.manager.login)

        if login_success:
            await self._safe_call(self.manager.update)
            self.is_connected = True
            
            # Dùng getattr để tránh lỗi nếu tài khoản chưa có thiết bị nào
            fans = getattr(self.manager, 'fans', [])
            
            print(f"[VeSync] Kết nối thành công! Đã tìm thấy {len(fans)} máy lọc không khí.")
            for fan in fans:
                print(f"   -> Tên thiết bị: '{fan.device_name}' (ID: {fan.cid})")
            return True
        else:
            print("[VeSync] ❌ Đăng nhập thất bại. Vui lòng kiểm tra lại Email/Mật khẩu.")
            return False

    def _get_purifier(self, device_id: str):
        if not self.manager or not self.is_connected:
            return None
        fans = getattr(self.manager, 'fans', [])
        for fan in fans:
            if fan.device_name == device_id or fan.cid == device_id:
                return fan
        return None

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        purifier = self._get_purifier(device_id)
        if purifier:
            await self._safe_call(purifier.update)
            return {
                "device_id": device_id,
                "status": "ON" if purifier.device_status == "on" else "OFF",
                "mode": getattr(purifier, 'mode', 'unknown'),
                "speed": getattr(purifier, 'fan_level', 'unknown')
            }
        return {"device_id": device_id, "status": "offline"}

    async def turn_on(self, device_id: str) -> bool:
        purifier = self._get_purifier(device_id)
        if purifier:
            print(f"[VeSync] Đang gửi lệnh BẬT cho máy lọc: {device_id}")
            return await self._safe_call(purifier.turn_on)
        print(f"[VeSync] ❌ Không tìm thấy thiết bị: {device_id}")
        return False

    async def turn_off(self, device_id: str) -> bool:
        purifier = self._get_purifier(device_id)
        if purifier:
            print(f"[VeSync] Đang gửi lệnh TẮT cho máy lọc: {device_id}")
            return await self._safe_call(purifier.turn_off)
        print(f"[VeSync] ❌ Không tìm thấy thiết bị: {device_id}")
        return False