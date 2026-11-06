import asyncio
import os
from tuya_connector import TuyaOpenAPI
from .base_connector import DeviceConnector
from typing import Dict, Any, Optional

from .tuya_connector import fetch_tuya_logs

# Giá trị DP `feed_state` theo spec thiết bị (GET .../specification).
_FEED_STATES = ("standby", "feeding", "done")

# Số phần tối đa cho 1 lần nhả (UI dùng 1-3). Khớp services/device_actions.py.
_MAX_PORTIONS = 10

# Mỗi call HTTP tới Tuya Cloud (client đồng bộ chạy trong thread). Không có timeout
# thì 1 request treo giữ thread + request API mãi — cùng ngưỡng với TuyaConnector.
_CALL_TIMEOUT_SECONDS = 15

class RojecoConnector(DeviceConnector):
    def __init__(self):
        self.is_connected = False
        
        # Credential đọc từ biến môi trường (dùng chung app Tuya với TuyaConnector).
        self.ACCESS_ID = os.getenv("TUYA_ACCESS_ID", "")
        self.ACCESS_KEY = os.getenv("TUYA_ACCESS_KEY", "")

        # Endpoint chuẩn cho Singapore Data Center
        self.API_ENDPOINT = os.getenv("TUYA_API_ENDPOINT", "https://openapi-sg.iotbing.com/")
        
        self.openapi = TuyaOpenAPI(self.API_ENDPOINT, self.ACCESS_ID, self.ACCESS_KEY)

    async def _call(self, fn, *args):
        """Client đồng bộ (requests) -> thread, có timeout: không block event loop, không treo mãi."""
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), _CALL_TIMEOUT_SECONDS)

    async def connect(self) -> bool:
        try:
            # Client đồng bộ (requests) -> chạy trong thread, không block event loop.
            result = await self._call(self.openapi.connect)
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

    async def fetch_event_logs(self, device_id: str, log_type: int, start_ms: int, end_ms: int,
                               size: int = 100) -> Optional[list]:
        """Nhật ký Tuya Cloud (CHỈ ĐỌC) — xem tuya_connector.fetch_tuya_logs."""
        async def call(fn, *args):
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), 15)

        async def ensure():
            if not self.is_connected:
                await call(self.openapi.connect)
                self.is_connected = True

        return await fetch_tuya_logs(call, self.openapi, device_id, log_type, start_ms, end_ms, size,
                                     ensure=ensure)

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        """
        Trạng thái thật của máy cho ăn từ Tuya Cloud (category `cwwsq`).

        Máy KHÔNG báo mức hạt hay pin — chỉ có:
          - `online` (thông tin thiết bị) -> status ON (sẵn sàng) / offline
          - DP `feed_state`: standby | feeding | done
          - DP `feed_report`: số phần vừa nhả ở lần cho ăn gần nhất
        status giữ nghĩa cũ "ON = sẵn sàng" để header đếm "Đang bật" không đổi.
        """
        try:
            if not self.is_connected:
                await self._call(self.openapi.connect)

            # Client đồng bộ -> chạy 2 request song song trong thread.
            info, status = await asyncio.gather(
                self._call(self.openapi.get, f'/v1.0/iot-03/devices/{device_id}'),
                self._call(self.openapi.get, f'/v1.0/iot-03/devices/{device_id}/status'),
            )

            online = bool((info.get('result') or {}).get('online')) if info.get('success') else False
            if not online or not status.get('success'):
                return {"device_id": device_id, "status": "offline"}

            dps = {item.get('code'): item.get('value') for item in status.get('result', [])}
            feed_state = str(dps.get('feed_state') or '').lower()
            if feed_state not in _FEED_STATES:
                print(f"[Rojeco] ⚠️ feed_state lạ/thiếu, dps={dps}")
                feed_state = "unknown"

            last_feed = dps.get('feed_report')
            try:
                last_feed = int(last_feed) if last_feed is not None else None
            except (TypeError, ValueError):
                last_feed = None

            return {
                "device_id": device_id,
                "status": "ON",
                "feed_state": feed_state,
                "last_feed": last_feed,
            }
        except Exception as e:
            print(f"[Rojeco] Lỗi đọc trạng thái: {e}")
            return {"device_id": device_id, "status": "offline"}

    async def turn_on(self, device_id: str) -> bool:
        return await self.set_mode(device_id, "1")

    async def turn_off(self, device_id: str) -> bool:
        # Máy cho ăn không có lệnh "tắt". Trước đây trả True -> app báo
        # "Đã tắt" dù không có gì xảy ra.
        return False

    async def set_mode(self, device_id: str, mode: str) -> bool:
        try:
            if not self.is_connected:
                await self._call(self.openapi.connect)

            # Chuyển mode sang số nguyên (portions). Chặn số vô lý ngay tại đây
            # (spec máy cho tới 40 phần — 1 lệnh sai là đổ cả khay hạt).
            portions = int(mode)
            if not 1 <= portions <= _MAX_PORTIONS:
                print(f"[Rojeco] Từ chối số phần không hợp lệ: {portions}")
                return False

            # Cấu trúc Body chuẩn theo ảnh Debug của bạn
            commands = {'commands': [{'code': 'manual_feed', 'value': portions}]}

            # ĐƯỜNG DẪN CHUẨN: /v1.0/iot-03/...
            endpoint = f'/v1.0/iot-03/devices/{device_id}/commands'
            # Client đồng bộ -> chạy trong thread để không block event loop.
            response = await self._call(self.openapi.post, endpoint, commands)
            
            print(f"[Rojeco] Gửi lệnh thành công: {response}")
            return response.get('success', False)
        except Exception as e:
            print(f"[Rojeco] Lỗi: {e}")
            return False