# backend/app/models/device.py
from sqlalchemy import Column, String, Boolean
from app.core.database import Base

class DeviceModel(Base):
    __tablename__ = "devices"

    # ??nh ngh?a c?c c?t trong b?ng SQL
    id = Column(String, primary_key=True, index=True) # VD: 'den_phong_khach'
    name = Column(String, nullable=False)             # VD: '??n Ph?ng Kh?ch'
    brand = Column(String, nullable=False)            # VD: 'tuya' hay 'vesync'
    is_active = Column(Boolean, default=True)         # Tr?ng th?i thi?t b? c? ?ang d?ng kh?ng