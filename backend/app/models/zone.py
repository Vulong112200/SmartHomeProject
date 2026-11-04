# backend/app/models/zone.py
from sqlalchemy import Column, ForeignKey, Integer, String

from app.core.database import Base


class ZoneModel(Base):
    """
    Một khu vực trong nhà (Phòng khách, Phòng ngủ, Bếp...).

    Thiết bị thuộc khu; thành viên được cấp quyền theo khu. Cấp theo khu chứ
    không theo từng thiết bị vì danh sách ổ cắm sẽ phình ra: per-device là
    O(thành viên × thiết bị) hàng phải bảo trì mỗi lần mua thêm ổ cắm, còn
    per-zone thì thiết bị mới THỪA HƯỞNG quyền từ phòng.
    """

    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)  # thứ tự hiển thị


class MemberZoneAccessModel(Base):
    """
    Grant: thành viên `user_id` được dùng khu `zone_id`.

    Chỉ áp dụng cho kid/guest — owner/adult thấy mọi khu theo luật vai, không
    cần hàng nào ở đây.

    Không có cột `can_control` (tách xem với điều khiển): nhân đôi bề mặt kiểm
    tra quyền cho một phân biệt mà 4 người trong nhà sẽ không dùng tới.
    """

    __tablename__ = "member_zone_access"

    user_id = Column(
        String,
        ForeignKey("members.user_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    zone_id = Column(
        Integer,
        ForeignKey("zones.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
