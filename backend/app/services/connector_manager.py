# backend/app/services/connector_manager.py
import logging
import os

from .base_connector import DeviceConnector

logger = logging.getLogger("SmartHome.Connectors")


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


async def register_default_connectors(manager: ConnectorManager = device_manager) -> None:
    """
    Khởi tạo + đăng ký 3 connector của nhà (Tuya / VeSync / Rojeco).

    Dùng chung cho FastAPI (lifespan) và worker hẹn giờ tại nhà — MỘT bản
    connector, không có bản sao thứ hai. Credential đọc từ biến môi trường lúc
    khởi tạo, nên người gọi phải load_dotenv TRƯỚC.

    Lỗi 1 hãng không làm hỏng hãng khác. Đăng ký TRƯỚC khi connect: connect lỗi
    (mất mạng lúc boot) thì connector vẫn có mặt và tự thử lại khi có lệnh,
    thay vì "chưa hỗ trợ hãng" tới khi restart.
    """
    # Import trễ: module này phải nạp được mà không kéo theo SDK của các hãng.
    from .rojeco_connector import RojecoConnector
    from .tuya_connector import TuyaConnector
    from .vesync_connector import VeSyncConnector

    factories = (
        ("tuya", TuyaConnector),
        ("vesync", lambda: VeSyncConnector(
            email=os.getenv("VESYNC_EMAIL", ""),
            password=os.getenv("VESYNC_PASSWORD", ""),
        )),
        ("rojeco", RojecoConnector),
    )
    for brand, factory in factories:
        try:
            plugin = factory()
            manager.register_connector(brand, plugin)
            ok = await plugin.connect()
            if not ok:
                logger.warning(f"Connector {brand} kết nối KHÔNG thành công (sẽ thử lại khi có lệnh).")
        except Exception as e:
            logger.error(f"Lỗi khởi động connector {brand}: {e}")
