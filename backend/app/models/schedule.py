# backend/app/models/schedule.py
from sqlalchemy import Column, Integer, String, Boolean
from app.core.database import Base

class ScheduleModel(Base):
    """
    Một lịch Hẹn giờ ĐƠN: 1 thiết bị + 1 giờ + 1 hành động (+ ngày lặp).
    Kịch bản nhiều bước (vd 4h30 lọc cao -> 6h30 auto) = tạo nhiều lịch.
    """
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String, default="")                 # Nhãn tùy chọn, vd "Bật lọc mạnh sáng"
    brand = Column(String, nullable=False)            # tuya | vesync | rojeco
    device_id = Column(String, nullable=False)
    action_type = Column(String, nullable=False)      # on | off | mode
    action_value = Column(String, nullable=True)      # mode: 1/2/3/auto/sleep/open/close/stop; on/off = null
    time = Column(String, nullable=False)             # "HH:MM" giờ Asia/Ho_Chi_Minh
    days = Column(String, default="")                 # CSV weekday Python (0=Thứ2..6=CN); rỗng = mỗi ngày
    enabled = Column(Boolean, default=True)
    last_fired_date = Column(String, nullable=True)   # "YYYY-MM-DD" — chống kích hoạt trùng trong ngày
