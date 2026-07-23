# backend/app/services/connector_factory.py
"""
Phân giải connector THEO NGƯỜI DÙNG.

Nhận xét quan trọng:
  * Tuya/Rojeco: điều khiển & đọc trạng thái chỉ cần device_id + token PROJECT
    dùng chung (thiết bị đã hiện dưới project sau khi chủ liên kết QR). => giữ
    connector Tuya/Rojeco là singleton toàn app (đăng ký ở connector_manager).
  * VeSync: đăng nhập theo TỪNG tài khoản user => cần connector riêng mỗi user,
    tạo từ credential (đã mã hóa) trong bảng vendor_accounts, cache để khỏi
    login lại mỗi lệnh.

Do đó factory chỉ thực sự "per-user" cho VeSync; các brand Tuya-based trả về
singleton chung.
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.crypto import decrypt_json
from app.models.vendor_account import VendorAccountModel
from .connector_manager import device_manager
from .vesync_connector import VeSyncConnector

logger = logging.getLogger("SmartHome.ConnectorFactory")

# Cache connector VeSync theo user_id (đã login). {user_id: VeSyncConnector}
_vesync_cache: dict[str, VeSyncConnector] = {}

# Brand dùng chung project Tuya (singleton).
_TUYA_BRANDS = {"tuya", "rojeco"}


def invalidate_user(user_id: str) -> None:
    """Xóa cache khi user đổi credential VeSync (buộc login lại lần sau)."""
    _vesync_cache.pop(user_id, None)


def _load_vesync_creds(db: Session, user_id: str) -> Optional[dict]:
    acc = (db.query(VendorAccountModel)
             .filter(VendorAccountModel.user_id == user_id,
                     VendorAccountModel.brand == "vesync")
             .first())
    if not acc or not acc.credentials_encrypted:
        return None
    return decrypt_json(acc.credentials_encrypted)


async def get_user_connector(db: Session, user_id: str, brand: str):
    """
    Trả connector phù hợp để điều khiển/đọc trạng thái thiết bị của user.
    Ném ValueError nếu brand không hỗ trợ hoặc user chưa kết nối VeSync.
    """
    brand = (brand or "").lower()

    if brand in _TUYA_BRANDS:
        # Singleton chung — connector tự lazy-connect khi có lệnh nếu chưa kết nối.
        return device_manager.get_connector(brand)

    if brand == "vesync":
        conn = _vesync_cache.get(user_id)
        if conn is not None and conn.is_connected:
            return conn
        creds = _load_vesync_creds(db, user_id)
        if not creds or not creds.get("email"):
            raise ValueError("Bạn chưa kết nối tài khoản VeSync.")
        conn = VeSyncConnector(email=creds["email"], password=creds.get("password", ""))
        ok = await conn.connect()
        if not ok:
            _vesync_cache.pop(user_id, None)
            raise ValueError("Đăng nhập VeSync thất bại (email/mật khẩu?).")
        _vesync_cache[user_id] = conn
        return conn

    raise ValueError(f"Hệ thống chưa hỗ trợ thiết bị của hãng: {brand}")


async def discover_vesync(email: str, password: str) -> list:
    """Login tạm 1 lần để lấy danh sách thiết bị VeSync (KHÔNG cache/persist)."""
    conn = VeSyncConnector(email=email, password=password)
    ok = await conn.connect()
    if not ok:
        raise ValueError("Đăng nhập VeSync thất bại. Kiểm tra lại email/mật khẩu.")
    return conn.list_devices()
