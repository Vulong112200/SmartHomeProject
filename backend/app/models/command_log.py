# backend/app/models/command_log.py
from sqlalchemy import BigInteger, Boolean, Column, Integer, String

from app.core.database import Base


class CommandLogModel(Base):
    """
    Lịch sử lệnh điều khiển / thay đổi trạng thái thiết bị — để biết app đang
    được dùng thế nào (ai bấm, bấm từ đâu, lúc nào, có ăn không).

    Hai loại hàng:
      - Lệnh do HỆ THỐNG này gửi (app/widget/shortcut/giọng nói/kịch bản/lịch):
        ghi ngay lúc gửi, có `success` và người gửi.
      - Sự kiện QUAN SÁT được từ bên ngoài (nút vật lý, công tắc tường, app
        Smart Life, lịch cài trong máy...): đọc lại từ nhật ký Tuya Cloud hoặc
        phát hiện qua đổi trạng thái (VeSync). `success` NULL, `ext_id` chống
        ghi trùng khi đồng bộ lại.

    `device_name` / `user_name` là ẢNH CHỤP lúc ghi: đổi tên thiết bị hay
    người dùng sau này không làm sai lịch sử cũ.
    `at_ms` = epoch mili-giây UTC (cùng đơn vị với nhật ký Tuya, sắp xếp được
    trên cả SQLite lẫn Postgres mà không lo múi giờ).
    """

    __tablename__ = "command_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    at_ms = Column(BigInteger, nullable=False, index=True)
    device_id = Column(String, nullable=False, index=True)
    device_name = Column(String, nullable=True)
    action_type = Column(String, nullable=True)   # on | off | mode | event
    action_value = Column(String, nullable=True)
    action_label = Column(String, nullable=False)  # "Mở", "Bật", "Lọc Cao", "Cho ăn 2 phần"...
    # app | widget | shortcut | voice | scene | schedule | tuya_app | device | external
    source = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    user_name = Column(String, nullable=True)
    success = Column(Boolean, nullable=True)       # NULL = sự kiện quan sát, không phải lệnh
    detail = Column(String, nullable=True)         # câu nói, tên kịch bản/lịch, lỗi...
    ext_id = Column(String, nullable=True, unique=True)  # khóa chống trùng khi đồng bộ nhật ký ngoài
