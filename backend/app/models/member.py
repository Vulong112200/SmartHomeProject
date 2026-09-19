# backend/app/models/member.py
from sqlalchemy import Column, String

from app.core.database import Base


class MemberModel(Base):
    """
    Một thành viên trong nhà.

    Thay hẳn bảng `profiles` + trigger `handle_new_user()` + function `is_admin()`
    của thiết kế cũ: những thứ đó chỉ tồn tại để lấy email cho màn hình quản trị,
    mà lại bắt viết raw SQL có cast `id::text` cùng một nhánh riêng cho SQLite.

    `user_id` = `auth.users.id` của Supabase, lưu dạng text để SQLite dùng chung
    được (SQLite không có kiểu uuid).
    """

    __tablename__ = "members"

    user_id = Column(String, primary_key=True, index=True)
    email = Column(String, nullable=False, default="")
    display_name = Column(String, nullable=False, default="")

    # owner  — chủ nhà: thấy mọi khu + quản trị (thiết bị, khu, thành viên)
    # adult  — người lớn: thấy mọi khu, không quản trị
    # kid    — chỉ thấy khu được cấp
    # guest  — chỉ thấy khu được cấp, không tạo được lịch
    role = Column(String, nullable=False, default="guest")

    # pending — mới đăng nhập lần đầu, chờ chủ nhà duyệt (403 mọi nơi trừ /api/me)
    # active  — dùng bình thường
    # blocked — bị chặn
    status = Column(String, nullable=False, default="pending")


ROLES = ("owner", "adult", "kid", "guest")
STATUSES = ("pending", "active", "blocked")

# Vai thấy được MỌI khu vực, kể cả thiết bị chưa phân khu (zone_id IS NULL).
# kid/guest thì đi qua bảng grant member_zone_access.
ROLES_SEE_ALL_ZONES = ("owner", "adult")
