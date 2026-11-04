import asyncio
import os
import time
from tuya_connector import TuyaOpenAPI
from .base_connector import DeviceConnector
from typing import Dict, Any, Optional

# =========================================================
# Tên DP (data point) ứng viên cho cửa cuốn/rèm — tùy model Tuya khác nhau.
# Xem log "[Tuya Door] Status raw" để bổ sung tên nếu thiết bị của bạn dùng tên khác.
# Ưu tiên VỊ TRÍ/TÌNH TRẠNG THẬT do motor báo về; 'control' chỉ là LỆNH CUỐI
# echo trên cloud (có thể cũ/kẹt) nên chỉ dùng làm fallback cuối.
# =========================================================
# Vị trí thật 0-100. percent_state = vị trí HIỆN TẠI (ưu tiên hơn percent_control = target).
_POSITION_DPS = ("percent_state", "position", "curtain_position", "percent_control")
# Một số model báo thẳng tình trạng (opening/closing/open/closed/stop...).
_WORK_STATE_DPS = ("work_state", "doorcontrol_state", "situation_set", "door_state")
# Map giá trị work_state thô -> door_state chuẩn của app.
_WORK_STATE_MAP = {
    "open": "open", "opened": "open", "fully_open": "open",
    "close": "closed", "closed": "closed", "fully_close": "closed",
    "opening": "opening", "closing": "closing",
    "stop": "stopped", "pause": "stopped", "stopped": "stopped",
}

# Thời gian cửa chạy hết hành trình (log thật: mở ~24s, đóng ~16s). Lệnh
# open/close cuối đã cũ hơn mốc này -> báo "Đã mở"/"Đã đóng" thay vì kẹt mãi ở
# "Đang mở..."/"Đang đóng...".
_DOOR_TRAVEL_SECONDS = 30

# tuya-connector-python gọi requests KHÔNG có timeout: 1 call treo là treo luôn
# scheduler (các hành động chạy nối tiếp). Cắt ở mốc này.
_CALL_TIMEOUT_SECONDS = 15

# Category Tuya của công tắc/ổ cắm bật-tắt đơn (vd. máy bơm tăng áp dùng 'tdq').
# Thiết bị thuộc các loại này điều khiển bằng DP 'switch_1' thay vì 'control'.
_SWITCH_CATEGORIES = ("kg", "tdq", "cz", "pc", "dlq")

class TuyaConnector(DeviceConnector):
    def __init__(self):
        self.is_connected = False
        
        # Credential đọc từ biến môi trường (backend/.env local, hoặc Render dashboard).
        self.ACCESS_ID = os.getenv("TUYA_ACCESS_ID", "")
        self.ACCESS_KEY = os.getenv("TUYA_ACCESS_KEY", "")

        # Data Center Singapore
        self.API_ENDPOINT = os.getenv("TUYA_API_ENDPOINT", "https://openapi-sg.iotbing.com/")
        
        self.openapi = TuyaOpenAPI(self.API_ENDPOINT, self.ACCESS_ID, self.ACCESS_KEY)

        # device_id -> category Tuya. Loại thiết bị không đổi nên tra 1 lần là đủ.
        self._categories: Dict[str, str] = {}

    async def _call(self, fn, *args):
        """Client đồng bộ (requests) -> chạy trong thread (không block event loop), có timeout."""
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), _CALL_TIMEOUT_SECONDS)

    async def _ensure_connected(self) -> None:
        if not self.is_connected:
            result = await self._call(self.openapi.connect)
            self.is_connected = bool(result.get("success")) if isinstance(result, dict) else True

    async def _is_switch(self, device_id: str) -> Optional[bool]:
        """
        Công tắc (switch_1) hay cửa cuốn (control)? Tra category 1 lần rồi cache.
        None = KHÔNG BIẾT (Tuya lỗi/timeout): người gọi phải từ chối gửi lệnh —
        đoán "là cửa" từng khiến máy bơm nhận lệnh control:open.
        """
        if device_id not in self._categories:
            try:
                await self._ensure_connected()
                info = await self._call(self.openapi.get, f'/v1.0/devices/{device_id}')
            except Exception as e:
                print(f"[Tuya] Lỗi tra loại thiết bị {device_id}: {e}")
                return None
            if not info.get('success'):
                return None  # không cache: lần sau thử lại
            self._categories[device_id] = str((info.get('result') or {}).get('category', ''))
        return self._categories[device_id] in _SWITCH_CATEGORIES

    async def _switch_state(self, device_id: str) -> Dict[str, Any]:
        """Công tắc: 1 lần gọi /v1.0/devices/{id} trả cả online lẫn DP switch_1."""
        info = await self._call(self.openapi.get, f'/v1.0/devices/{device_id}')
        result = info.get('result') or {}
        if not info.get('success') or not result.get('online'):
            return {"device_id": device_id, "status": "offline"}
        dps = {item.get('code'): item.get('value') for item in result.get('status', [])}
        if 'switch_1' not in dps:
            print(f"[Tuya Switch] ⚠️ Không thấy DP switch_1, dps={dps}")
            return {"device_id": device_id, "status": "offline"}
        return {"device_id": device_id, "status": "ON" if dps['switch_1'] else "OFF"}

    async def _send_switch(self, device_id: str, on: bool) -> bool:
        commands = {'commands': [{'code': 'switch_1', 'value': on}]}
        endpoint = f'/v1.0/iot-03/devices/{device_id}/commands'
        response = await self._call(self.openapi.post, endpoint, commands)
        print(f"[Tuya Switch] Gửi switch_1={on}: {response}")
        return response.get('success', False)

    async def connect(self) -> bool:
        try:
            # Client đồng bộ (requests) -> chạy trong thread, không block event loop.
            result = await self._call(self.openapi.connect)
            print("[Tuya Token Response]", result)
            # Chỉ đánh dấu connected khi Tuya thật sự cấp token thành công.
            self.is_connected = bool(result.get("success")) if isinstance(result, dict) else True
            if self.is_connected:
                print("[Tuya] ✅ Đã kết nối Tuya Cloud!")
            else:
                print(f"[Tuya] ❌ Tuya từ chối cấp token: {result}")
            return self.is_connected
        except Exception as e:
            print(f"[Tuya] ❌ Lỗi kết nối Tuya Cloud: {e}")
            return False

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        """
        Lấy trạng thái thật của cửa cuốn từ Tuya Cloud.
        Endpoint: GET /v1.0/iot-03/devices/{id}/status -> list các DP {code, value}.
        Lưu ý: tên DP tùy thiết bị. In log 1 lần để xác nhận nếu map chưa đúng.
        """
        try:
            await self._ensure_connected()

            is_switch = await self._is_switch(device_id)
            if is_switch is None:
                return {"device_id": device_id, "status": "offline"}
            if is_switch:
                return await self._switch_state(device_id)

            # shadow/properties trả kèm THỜI ĐIỂM mỗi DP được báo lần cuối — cần để
            # biết lệnh 'control' cuối đã đủ lâu cho cửa chạy xong hay chưa.
            # tuya-connector-python là client đồng bộ (requests) -> chạy trong thread
            # để không block event loop, tránh các request khác xếp hàng nối tiếp.
            response = await self._call(
                self.openapi.get, f'/v2.0/cloud/thing/{device_id}/shadow/properties'
            )
            print(f"[Tuya Door] Status raw: {response}")

            if not response.get('success'):
                return {"device_id": device_id, "status": "offline"}

            # Chuyển list DP thành dict cho dễ tra cứu
            props = (response.get('result') or {}).get('properties', [])
            dps = {item.get('code'): item.get('value') for item in props}
            control_ms = next((p.get('time') for p in props if p.get('code') == 'control'), None)

            # DP điều khiển gần nhất: 'open' | 'close' | 'stop' (chỉ là lệnh cuối)
            control = str(dps.get('control', '')).lower()
            # Lệnh cuối đã qua đủ thời gian chạy hết hành trình -> coi như cửa đã tới nơi.
            settled = control_ms is not None and time.time() - control_ms / 1000 >= _DOOR_TRAVEL_SECONDS

            # 1) VỊ TRÍ THẬT do motor báo về (đáng tin nhất) — thử lần lượt các tên DP.
            position = None
            for code in _POSITION_DPS:
                if dps.get(code) is not None:
                    try:
                        position = int(dps[code])
                        break
                    except (TypeError, ValueError):
                        continue

            # 2) DP tình trạng thật (nếu model báo trực tiếp).
            work_state = ""
            for code in _WORK_STATE_DPS:
                if dps.get(code) is not None:
                    work_state = str(dps[code]).lower()
                    break

            # Suy ra door_state: ưu tiên vị trí thật -> tình trạng thật -> lệnh cuối.
            door_state = None
            if position is not None:
                if position >= 100:
                    door_state = "open"
                elif position <= 0:
                    door_state = "closed"
                else:
                    door_state = "partial"
            elif work_state:
                door_state = _WORK_STATE_MAP.get(work_state)

            # 3) Fallback CUỐI: 'control' = lệnh cuối (từ app, app Tuya hoặc nút trên
            # công tắc tường). Model 'Curtain switch' hiện tại CHỈ có DP này. Bấm
            # remote RF điều khiển thẳng motor thì cloud không hề biết.
            if door_state is None:
                if control == "open":
                    door_state = "open" if settled else "opening"
                elif control == "close":
                    door_state = "closed" if settled else "closing"
                elif control == "stop":
                    door_state = "stopped"
                else:
                    door_state = "unknown"
                    print(f"[Tuya Door] ⚠️ Không nhận ra DP trạng thái/vị trí, dps={dps}")

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
        is_switch = await self._is_switch(device_id)
        if is_switch is None:
            return False  # không biết loại -> không đoán, không gửi gì
        return await self.set_mode(device_id, "on" if is_switch else "open")

    async def turn_off(self, device_id: str) -> bool:
        is_switch = await self._is_switch(device_id)
        if is_switch is None:
            return False
        return await self.set_mode(device_id, "off" if is_switch else "close")

    async def _send_control(self, device_id: str, value: str):
        """Gửi 1 lệnh 'control' tới Tuya Cloud và trả về response gốc."""
        commands = {'commands': [{'code': 'control', 'value': value}]}
        # ĐƯỜNG DẪN CHUẨN: /v1.0/iot-03/...
        endpoint = f'/v1.0/iot-03/devices/{device_id}/commands'
        response = await self._call(self.openapi.post, endpoint, commands)
        print(f"[Tuya Door] Gửi lệnh {value}: {response}")
        return response

    async def set_mode(self, device_id: str, mode: str) -> bool:
        try:
            await self._ensure_connected()

            mode = mode.lower()
            is_switch = await self._is_switch(device_id)
            if is_switch is None:
                print(f"[Tuya] Không xác định được loại {device_id} -> KHÔNG gửi lệnh {mode}")
                return False

            # Công tắc: chỉ có on/off. KHÔNG bao giờ gửi 'control' (lệnh cửa) tới nó.
            if is_switch:
                if mode not in ("on", "off"):
                    print(f"[Tuya Switch] Bỏ qua mode không hợp lệ cho công tắc: {mode}")
                    return False
                return await self._send_switch(device_id, mode == "on")

            # Với cửa cuốn, mode là 'open', 'close', 'stop'
            if mode not in ("open", "close", "stop"):
                print(f"[Tuya Door] Bỏ qua mode không hợp lệ cho cửa: {mode}")
                return False

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