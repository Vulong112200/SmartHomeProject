# backend/app/models/device.py
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String

from app.core.database import Base


class DeviceModel(Base):
    __tablename__ = "devices"

    # PK = id THẬT của hãng (vd 'a32aae46a67dbe52860pza').
    # ⚠️ Không đổi sang surrogate PK: schedules.device_id, local_parser,
    # DeviceOrder, shortcut ĐÃ PIN trên màn hình chính và Home Widget đều tham
    # chiếu id này — đổi là mồ côi hết shortcut/widget trên điện thoại cả nhà.
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)              # vd 'Cửa cuốn'
    brand = Column(String, nullable=False)             # tuya | vesync | rojeco
    is_active = Column(Boolean, default=True)

    # Khu vực chứa thiết bị. NULL = "hộp thư đến": thiết bị vừa import chưa được
    # gán phòng, chỉ owner/adult thấy. Điều này rơi ra miễn phí từ INNER JOIN
    # trong household.device_query — không cần case đặc biệt.
    # ondelete SET NULL: xóa khu thì thiết bị về hộp thư đến, không bị xóa theo.
    zone_id = Column(
        Integer,
        ForeignKey("zones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Loại thiết bị do chủ nhà đặt, một trong DEVICE_CATEGORIES.
    # NULL = để client tự suy từ tên như cũ (core/device_type.dart).
    category = Column(String, nullable=True)


# Loại thiết bị hợp lệ — khớp enum DeviceType phía client (core/device_type.dart).
# Thêm loại mới thì phải sửa CẢ HAI nơi, nếu không app coi là "unknown".
DEVICE_CATEGORIES = ("purifier", "curtain", "feeder")
