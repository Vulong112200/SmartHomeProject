# backend/app/core/household.py
"""
NƠI DUY NHẤT quyết định quyền trong nhà.

Mô hình: **thiết bị thuộc khu vực, thành viên được cấp quyền theo khu vực.**
Không có bảng `homes` — một cột luôn bằng 1 trên mọi bảng là trả giá ngay để
dùng sau nhiều năm. Điều làm "nhiều nhà" rẻ về sau không phải cái bảng đó, mà
là dồn hết logic scoping vào đúng file này: lúc cần chỉ thêm cột `home_id` và
sửa 2 hàm, không phải sửa endpoint nào.

Ma trận quyền:

|                                         | owner | adult | kid | guest/pending |
|-----------------------------------------|-------|-------|-----|---------------|
| Thấy + điều khiển thiết bị trong khu Z   | mọi   | mọi   | nếu được cấp Z | nếu được cấp Z |
| Thiết bị zone_id IS NULL (chưa phân khu) | ✅    | ✅    | ❌  | ❌            |
| Tạo/sửa lịch cho thiết bị mình dùng được | ✅    | ✅    | ✅  | ❌            |
| Sửa/xóa lịch NGƯỜI KHÁC tạo              | ✅    | ✅    | ❌  | ❌            |
| Thêm/xóa thiết bị, khu, thành viên       | ✅    | ❌    | ❌  | ❌            |

Hai tính chất đáng chú ý:
  1. Vai và grant đọc từ DB MỖI REQUEST ⇒ duyệt / đổi vai / chặn có hiệu lực
     ngay ở request kế tiếp, không bắt đăng nhập lại (khác với nhét role vào JWT).
  2. Quyền KHÔNG BAO GIỜ xuất hiện trong thân endpoint — endpoint chỉ gọi
     `device_query` / `require_device_access` / `require_owner`.
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_db
from app.models.device import DeviceModel
from app.models.member import ROLES_SEE_ALL_ZONES, MemberModel
from app.models.schedule import ScheduleModel
from app.models.zone import MemberZoneAccessModel, ZoneModel

# Vai được quản trị: thêm/xóa thiết bị, khu vực, thành viên, quét thiết bị.
_ADMIN_ROLES = ("owner",)
# Vai được tạo/sửa lịch hẹn. guest chỉ xem.
_CAN_SCHEDULE_ROLES = ("owner", "adult", "kid")
# Vai được sửa/xóa lịch do NGƯỜI KHÁC tạo.
_CAN_EDIT_OTHERS_SCHEDULE = ("owner", "adult")

_PENDING_MESSAGE = "Đang chờ chủ nhà phê duyệt."
_BLOCKED_MESSAGE = "Tài khoản đã bị chặn."


# =========================================================
# Tạo / lấy thành viên
# =========================================================
def provision_member(db: Session, user: CurrentUser) -> MemberModel:
    """
    Trả hàng `members` của user, tự tạo nếu đăng nhập lần đầu.

    Người lạ lần đầu -> guest/pending, 0 grant: đăng nhập được, /api/me được,
    mọi endpoint khác 403 -> app hiện màn hình chờ duyệt.

    Email trong ADMIN_EMAILS thì LUÔN được nâng lên owner/active, kể cả khi
    hàng đã tồn tại với vai thấp hơn. Đây là cứu hộ: chủ nhà không bao giờ tự
    khóa mình khỏi nhà mình.
    """
    member = db.query(MemberModel).filter(MemberModel.user_id == user.user_id).first()

    if member is None:
        member = MemberModel(
            user_id=user.user_id,
            email=user.email,
            display_name=user.email.split("@")[0] if user.email else "",
            role="owner" if user.is_admin else "guest",
            status="active" if user.is_admin else "pending",
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    changed = False
    if user.is_admin and (member.role != "owner" or member.status != "active"):
        member.role = "owner"
        member.status = "active"
        changed = True
    # Email có thể đổi phía Supabase; giữ đồng bộ để màn hình quản trị không lệch.
    if user.email and member.email != user.email:
        member.email = user.email
        changed = True
    if changed:
        db.commit()
        db.refresh(member)
    return member


def get_member(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> MemberModel:
    """
    Thành viên hiện tại, KHÔNG chặn pending/blocked.

    Chỉ dùng cho `/api/me` — app cần đọc được trạng thái của chính mình để biết
    hiện màn hình chờ duyệt hay màn hình chính.
    """
    return provision_member(db, user)


def get_current_member(
    member: MemberModel = Depends(get_member),
) -> MemberModel:
    """Thành viên hiện tại, đã qua kiểm tra trạng thái. Dùng cho mọi endpoint khác."""
    if member.status == "blocked":
        raise HTTPException(status.HTTP_403_FORBIDDEN, _BLOCKED_MESSAGE)
    if member.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, _PENDING_MESSAGE)
    return member


def require_owner(
    member: MemberModel = Depends(get_current_member),
) -> MemberModel:
    """Chỉ chủ nhà: thêm/xóa thiết bị, quản lý khu vực và thành viên."""
    if member.role not in _ADMIN_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Chỉ chủ nhà mới làm được việc này."
        )
    return member


# =========================================================
# Phạm vi thiết bị
# =========================================================
def sees_all_zones(member: MemberModel) -> bool:
    return member.role in ROLES_SEE_ALL_ZONES


def device_query(db: Session, member: MemberModel):
    """
    Query các thiết bị mà `member` được phép thấy và điều khiển.

    owner/adult: tất cả, kể cả thiết bị chưa phân khu.
    kid/guest:   INNER JOIN grant theo khu — thiết bị `zone_id IS NULL` tự động
                 rơi ra ngoài, đúng ý "hộp thư đến chỉ chủ nhà thấy", không cần
                 viết case đặc biệt nào.
    """
    if sees_all_zones(member):
        return db.query(DeviceModel)
    return (
        db.query(DeviceModel)
        .join(MemberZoneAccessModel, MemberZoneAccessModel.zone_id == DeviceModel.zone_id)
        .filter(MemberZoneAccessModel.user_id == member.user_id)
    )


def require_device_access(db: Session, member: MemberModel, device_id: str) -> DeviceModel:
    """
    Thiết bị `device_id` nếu `member` được phép dùng, ngược lại ném lỗi.

    404 khi thiết bị không có trong nhà; 403 khi có nhưng ngoài khu của mình —
    trong nhà không cần giấu nhau việc thiết bị đó tồn tại.
    """
    device = device_query(db, member).filter(DeviceModel.id == device_id).first()
    if device is not None:
        return device

    exists = db.query(DeviceModel).filter(DeviceModel.id == device_id).first()
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thiết bị.")
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "Bạn không được cấp quyền cho khu vực của thiết bị này."
    )


def accessible_zones(db: Session, member: MemberModel) -> list[ZoneModel]:
    """Danh sách khu vực member được thấy, theo thứ tự hiển thị."""
    if sees_all_zones(member):
        return db.query(ZoneModel).order_by(ZoneModel.sort_order, ZoneModel.name).all()
    return (
        db.query(ZoneModel)
        .join(MemberZoneAccessModel, MemberZoneAccessModel.zone_id == ZoneModel.id)
        .filter(MemberZoneAccessModel.user_id == member.user_id)
        .order_by(ZoneModel.sort_order, ZoneModel.name)
        .all()
    )


# =========================================================
# Phạm vi lịch hẹn
# =========================================================
def schedule_query(db: Session, member: MemberModel):
    """
    Lịch của những thiết bị mà `member` dùng được.

    Lọc theo THIẾT BỊ chứ không theo người tạo: lịch hẹn là của cả nhà, ai nhìn
    thấy thiết bị thì nhìn thấy lịch của nó.
    """
    if sees_all_zones(member):
        return db.query(ScheduleModel)
    return (
        db.query(ScheduleModel)
        .join(DeviceModel, DeviceModel.id == ScheduleModel.device_id)
        .join(MemberZoneAccessModel, MemberZoneAccessModel.zone_id == DeviceModel.zone_id)
        .filter(MemberZoneAccessModel.user_id == member.user_id)
    )


def require_can_schedule(member: MemberModel) -> None:
    """guest chỉ xem, không tạo/sửa lịch."""
    if member.role not in _CAN_SCHEDULE_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Bạn không có quyền tạo hoặc sửa lịch hẹn."
        )


def require_schedule_write(db: Session, member: MemberModel, schedule_id: int) -> ScheduleModel:
    """
    Lịch `schedule_id` nếu `member` được phép sửa/xóa.

    Điều kiện: dùng được thiết bị của lịch, VÀ (là người tạo HOẶC có vai được
    sửa lịch người khác). kid tạo lịch của mình thì sửa được, nhưng không đụng
    được lịch bố mẹ đặt.
    """
    require_can_schedule(member)

    schedule = schedule_query(db, member).filter(ScheduleModel.id == schedule_id).first()
    if schedule is None:
        exists = db.query(ScheduleModel).filter(ScheduleModel.id == schedule_id).first()
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy lịch hẹn.")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Lịch này thuộc khu vực bạn không được cấp quyền."
        )

    if member.role in _CAN_EDIT_OTHERS_SCHEDULE:
        return schedule
    if schedule.created_by == member.user_id:
        return schedule
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "Bạn chỉ sửa được lịch do chính mình tạo."
    )


# =========================================================
# Serialize
# =========================================================
def member_to_dict(member: MemberModel, zone_ids: list[int] | None = None) -> dict:
    data = {
        "user_id": member.user_id,
        "email": member.email,
        "display_name": member.display_name,
        "role": member.role,
        "status": member.status,
        "can_admin": member.role in _ADMIN_ROLES,
        "can_schedule": member.role in _CAN_SCHEDULE_ROLES,
        "sees_all_zones": sees_all_zones(member),
    }
    if zone_ids is not None:
        data["zone_ids"] = zone_ids
    return data


def zone_ids_of(db: Session, user_id: str) -> list[int]:
    rows = (
        db.query(MemberZoneAccessModel.zone_id)
        .filter(MemberZoneAccessModel.user_id == user_id)
        .all()
    )
    return sorted(r[0] for r in rows)
