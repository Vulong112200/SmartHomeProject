# backend/app/services/connector_manager.py
from .base_connector import DeviceConnector

class ConnectorManager:
    def __init__(self):
        # Lưu trữ danh sách các plugin đã đăng ký
        self._connectors: dict[str, DeviceConnector] = {}

    def register_connector(self, brand_name: str, connector: DeviceConnector):
        """Đăng ký một plugin mới vào hệ thống"""
        self._connectors[brand_name] = connector
        print(f"Đã đăng ký Connector cho hệ sinh thái: {brand_name}")

    def get_connector(self, brand_name: str) -> DeviceConnector:
        """Lấy plugin tương ứng với tên hãng"""
        if brand_name not in self._connectors:
            raise ValueError(f"Hệ thống chưa hỗ trợ thiết bị của hãng: {brand_name}")
        return self._connectors[brand_name]

# Tạo một instance duy nhất (Singleton) để dùng chung cho toàn bộ app
device_manager = ConnectorManager()