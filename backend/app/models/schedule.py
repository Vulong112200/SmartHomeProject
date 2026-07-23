# backend/app/models/schedule.py
from sqlalchemy import Column, Integer, String, Boolean
from app.core.database import Base

class ScheduleModel(Base):
    """
    Một lịch Hẹn giờ: 1 thiết bị + giờ bắt đầu + hành động bắt đầu (+ ngày lặp).
    Lịch "KHOẢNG": thêm end_time + end_action_* — hành động thứ hai khi hết khoảng
    (vd 16:30 lọc Cao -> 17:30 lọc TB). end_time NULL = lịch đơn như cũ.
    end_time < time nghĩa là khoảng QUA ĐÊM: end kích hoạt vào ngày hôm sau.
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
    end_time = Column(String, nullable=True)          # "HH:MM"; NULL = lịch đơn
    end_action_type = Column(String, nullable=True)   # on | off | mode (bắt buộc khi có end_time)
    end_action_value = Column(String, nullable=True)
    last_end_fired_date = Column(String, nullable=True)  # chống bắn trùng cho hành động kết thúc
    one_shot = Column(Boolean, default=False)         # chạy 1 lần: tự enabled=False sau hành động cuối
