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

    @staticmethod
    def _read(obj, *names, default=None):
        """
        Đọc thuộc tính phòng thủ, hỗ trợ cả pyvesync 3.x (state runtime nằm trong
        device.state.*) lẫn ≤2.x (attr thẳng trên device). Ưu tiên `obj.state.<x>`
        TRƯỚC — vì ở 3.x các attr top-level (device_status/fan_level...) chỉ còn là
        property @deprecated trỏ về state, đọc thẳng state để tránh cảnh báo & sai lệch.
        Trả giá trị đầu tiên khác None.
        """
        state = getattr(obj, 'state', None)
        targets = [state, obj] if state is not None else [obj]
        for target in targets:
            for name in names:
                val = getattr(target, name, None)
                if val is not None:
                    return val
        return default

    async def connect(self) -> bool:
        print(f"[VeSync] Đang kết nối với tài khoản: {self.email}...")
        self.manager = VeSync(self.email, self.password, self.time_zone)
        
        login_success = await self._safe_call(self.manager.login)

        if login_success:
            await self._safe_call(self.manager.update)
            self.is_connected = True
            
            # 1. Lấy TẤT CẢ thiết bị trong tài khoản (Không phân biệt loại)
            all_devices = getattr(self.manager, 'devices', [])
            print(f"[VeSync] ✅ Kết nối thành công! Tổng số thiết bị trong tài khoản: {len(all_devices) if all_devices else 0}")
            
            if all_devices:
                print("[VeSync] --- DANH SÁCH CHI TIẾT THIẾT BỊ ---")
                for dev in all_devices:
                    try:
                        # In ra toàn bộ thông tin gốc để tìm CID (tên attr có thể đổi giữa các bản pyvesync)
                        name = getattr(dev, 'device_name', '?')
                        dtype = getattr(dev, 'device_type', '?')
                        cid = getattr(dev, 'cid', '?')
                        print(f"   -> Tên: '{name}' | Loại: '{dtype}' | CID: {cid}")
                    except Exception as e:
                        print(f"   -> (không đọc được thông tin thiết bị: {e})")
                print("-----------------------------------------")

            # 2. Vẫn kiểm tra nhóm fans như cũ
            fans = getattr(self.manager, 'fans', [])
            print(f"[VeSync] Số thiết bị được nhận diện là Máy lọc/Quạt: {len(fans)}")
            
            return True
        else:
            print("[VeSync] ❌ Đăng nhập thất bại. Vui lòng kiểm tra lại Email/Mật khẩu.")
            return False

    def _get_purifier(self, device_id: str):
        """Hàm tìm kiếm thiết bị linh hoạt trong toàn bộ tài khoản"""
        if not self.manager or not self.is_connected:
            return None

        # Lấy tất cả thiết bị (bao gồm cả những loại chưa phân loại)
        all_devices = getattr(self.manager, 'devices', [])
        
        for dev in all_devices:
            # Tìm theo CID (Ưu tiên) hoặc Tên thiết bị
            if getattr(dev, 'cid', None) == device_id or getattr(dev, 'device_name', None) == device_id:
                return dev
        return None

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        purifier = self._get_purifier(device_id)
        if not purifier:
            return {"device_id": device_id, "status": "offline"}
        try:
            await self._safe_call(purifier.update)

            # pyvesync 3.x chuyển trạng thái runtime vào purifier.state.*,
            # bản ≤2.x để thẳng trên purifier. _read() thử cả hai.
            raw_status = self._read(purifier, 'device_status', default='')
            mode = self._read(purifier, 'mode', default='unknown')
            speed = self._read(purifier, 'fan_level', 'speed', default='unknown')

            return {
                "device_id": device_id,
                "status": "ON" if str(raw_status).lower() == "on" else "OFF",
                "mode": mode,
                "speed": speed,
            }
        except Exception as e:
            print(f"[VeSync] Lỗi đọc trạng thái {device_id}: {e}")
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
    
    async def set_mode(self, device_id: str, mode: str) -> bool:
        purifier = self._get_purifier(device_id)
        if not purifier:
            print(f"[VeSync] ❌ Không tìm thấy thiết bị: {device_id}")
            return False
            
        mode = mode.lower()
        print(f"[VeSync] Đang đổi chế độ máy lọc {device_id} sang: {mode}")

        # Ưu tiên API mới của pyvesync 3.x (set_*), fallback về hàm cũ (deprecated)
        # nếu bản thư viện chưa có.
        def _method(*names):
            for n in names:
                fn = getattr(purifier, n, None)
                if fn is not None:
                    return fn
            return None

        if mode == "auto":
            fn = _method('set_auto_mode', 'auto_mode')
            return bool(await self._safe_call(fn)) if fn else False
        elif mode == "sleep":
            fn = _method('set_sleep_mode', 'sleep_mode')
            return bool(await self._safe_call(fn)) if fn else False
        elif mode in ["1", "2", "3", "4"]: # Tốc độ quạt (nút UI hiện dùng 1-3)
            level = int(mode)
            # Chỉ đặt nếu model hỗ trợ mức này (fan_levels tùy model: [1,2,3] hoặc [1,2,3,4]).
            levels = getattr(purifier, 'fan_levels', None)
            if levels and level not in levels:
                print(f"[VeSync] Model không hỗ trợ tốc độ {level} (fan_levels={list(levels)})")
                return False
            fn = _method('set_fan_speed', 'change_fan_speed')
            return bool(await self._safe_call(fn, level)) if fn else False

        return False