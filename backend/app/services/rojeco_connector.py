# backend/app/services/rojeco_connector.py
from .base_connector import DeviceConnector
from typing import Dict, Any

class RojecoConnector(DeviceConnector):
    def __init__(self):
        self.is_connected = False

    async def connect(self) -> bool:
        print("[Rojeco] ?? k?t n?i h? th?ng m?y cho th? c?ng ?n.")
        self.is_connected = True
        return True

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        return {"device_id": device_id, "status": "ON", "food_level": "OK"}

    async def turn_on(self, device_id: str) -> bool:
        # B?t = M?c ??nh cho ?n 1 ph?n
        return await self.feed(device_id, 1)

    async def turn_off(self, device_id: str) -> bool:
        print(f"[Rojeco] M?y cho ?n {device_id} ?ang ? ch? ?? ch?.")
        return True

    # H?m ??c th? c?a Rojeco: Cho ?n theo ph?n
    async def feed(self, device_id: str, portions: int) -> bool:
        if 1 <= portions <= 10:
            print(f"[Rojeco] ? ?? nh? {portions} ph?n th?c ?n cho ({device_id}).")
            # TODO: Sau n?y b?n s? g?n API th?t c?a Tuya/Rojeco v?o ??y
            return True
        else:
            print("[Rojeco] ? S? l??ng kh?u ph?n ph?i t? 1 ??n 10.")
            return False