# backend/app/models/vendor_account.py
from sqlalchemy import Column, String, Integer
from app.core.database import Base


class VendorAccountModel(Base):
    """
    Tài khoản nhà cung cấp mà 1 user đã kết nối.
      - VeSync: credentials_encrypted chứa {email, password} (Fernet) để re-login.
      - Tuya:   tuya_uid = uid tài khoản Smart Life đã liên kết vào project của bạn.
    1 user có tối đa 1 account mỗi brand (unique user_id+brand — đặt ở SQL Postgres;
    ở SQLite không ràng buộc cứng, xử lý upsert ở tầng app).
    """
    __tablename__ = "vendor_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    brand = Column(String, nullable=False)             # vesync | tuya
    credentials_encrypted = Column(String, nullable=True)  # Fernet token (VeSync)
    tuya_uid = Column(String, nullable=True)           # uid Tuya (Tuya)
    label = Column(String, default="")
    status = Column(String, default="connected")       # connected | error
    created_at = Column(String, nullable=True)
