# backend/app/services/base_connector.py
from abc import ABC, abstractmethod
from typing import Dict, Any

class DeviceConnector(ABC):
    """
    Lớp trừu tượng định nghĩa các hành động chuẩn mà MỌI thiết bị Smart Home đều phải có.
    """
    
    @abstractmethod
    async def connect(self) -> bool:
        """Khởi tạo kết nối với Cloud hoặc Local API của hãng"""
        pass

    @abstractmethod
    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        """Lấy trạng thái hiện tại của thiết bị (Bật/tắt, độ sáng, v.v.)"""
        pass

    @abstractmethod
    async def turn_on(self, device_id: str) -> bool:
        """Bật thiết bị"""
        pass

    @abstractmethod
    async def turn_off(self, device_id: str) -> bool:
        """Tắt thiết bị"""
        pass