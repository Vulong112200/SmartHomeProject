# backend/app/models/floor_plan.py
from sqlalchemy import BigInteger, Column, Integer, String, Text

from app.core.database import Base

# Nhà chỉ có MỘT sơ đồ (không có bảng homes) — luôn là hàng id = 1.
FLOOR_PLAN_ID = 1


class FloorPlanModel(Base):
    """
    Sơ đồ mặt bằng 2D của nhà: phòng (kích thước THẬT theo mét + vị trí tương
    đối giữa các phòng), cửa ra vào, và vị trí từng thiết bị trong phòng.

    `layout` là JSON text `{rooms, doors, devices}` đã được làm sạch bởi
    services/floor_plan.sanitize_layout. Lưu nguyên khối (như scenes.actions)
    vì sơ đồ luôn được đọc/ghi cả cụm trong 1 lần "Sửa sơ đồ → Lưu", không bao
    giờ truy vấn theo từng thiết bị.

    Không có hàng = chưa ai cấu hình ⇒ GET trả bố cục mặc định kèm
    `configured: false` để app nhắc chủ nhà đặt phòng/cửa/thiết bị cho đúng.

    Vị trí thiết bị KHÔNG có cột zone_id riêng: khu của thiết bị đã nằm ở
    devices.zone_id — chép sang đây chỉ tạo ra 2 nguồn sự thật lệch nhau.
    Thiết bị bị xóa / ngoài quyền được lọc lúc ĐỌC (giống members.sort_order).
    """

    __tablename__ = "floor_plans"

    id = Column(Integer, primary_key=True)
    layout = Column(Text, nullable=False)
    updated_by = Column(String, nullable=True)       # audit
    updated_at_ms = Column(BigInteger, nullable=True)
