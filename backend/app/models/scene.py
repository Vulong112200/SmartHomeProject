# backend/app/models/scene.py
from sqlalchemy import Column, Integer, String, Text

from app.core.database import Base


class SceneModel(Base):
    """
    Kịch bản: 1 nút chạy nhiều hành động (vd "Ra khỏi nhà" = đóng cửa + tắt máy
    lọc + tắt máy bơm).

    `actions` là JSON text `[{"device_id", "action_type", "action_value"}]` —
    đã CHUẨN HÓA qua services/device_actions.normalize_action lúc lưu, nên khi
    chạy không phải đoán. Lưu JSON thay vì bảng con vì kịch bản luôn được đọc/
    ghi nguyên khối, không bao giờ truy vấn theo từng hành động.

    Không gắn khu: kịch bản là của cả nhà. Ai cũng chạy được, nhưng chỉ những
    hành động trên thiết bị người đó dùng được (core/household.py quyết định).
    """

    __tablename__ = "scenes"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String, nullable=False)
    icon = Column(String, nullable=True)        # tên icon Material phía app; NULL = icon mặc định
    sort_order = Column(Integer, nullable=False, default=0)
    actions = Column(Text, nullable=False, default="[]")
    created_by = Column(String, nullable=True)  # chỉ để audit
    # Điều kiện chạy: JSON text {"operator": "AND"|"OR", "items": [...]} đã chuẩn
    # hóa (services/scene_condition_engine.py). NULL = không điều kiện — kịch bản
    # cũ giữ nguyên hành vi. Thêm bằng run_startup_migrations (bảng đã có).
    conditions = Column(Text, nullable=True)
