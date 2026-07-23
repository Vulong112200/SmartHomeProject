# backend/app/models/device.py
from sqlalchemy import Column, String, Boolean, Integer
from app.core.database import Base

class DeviceModel(Base):
    __tablename__ = "devices"

    # id = ID thiết bị của hãng (vendor device id): Tuya device id / VeSync cid /
    # slug cũ. Giữ làm PK để local_parser / scheduler không phải đổi.
    id = Column(String, primary_key=True, index=True)   # VD: 'den_phong_khach'
    user_id = Column(String, nullable=False, index=True, default="")  # chủ sở hữu (auth.users.id)
    name = Column(String, nullable=False)               # VD: 'Đèn Phòng Khách'
    brand = Column(String, nullable=False)              # tuya | vesync | rojeco
    category = Column(String, nullable=True)            # tùy chọn: purifier | curtain | feeder
    is_active = Column(Boolean, default=True)           # thiết bị có đang dùng không
    sort_order = Column(Integer, default=0)             # thứ tự hiển thị (kéo-thả)
    created_at = Column(String, nullable=True)          # ISO time (tùy chọn)
