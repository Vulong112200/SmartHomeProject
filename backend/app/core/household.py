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
| Thiết bị trong khu DÙNG CHUNG (is_shared) | ✅   | ✅    | ✅  | ✅ (active)   |
| Tạo/sửa/xóa kịch bản                     | ✅    | ✅    | ❌  | ❌            |
| Chạy kịch bản (chỉ phần thiết bị mình dùng được) | ✅ | ✅ | ✅ | ✅       |
| Thêm/xóa thiết bị, khu, thành viên       | ✅    | ❌    | ❌  | ❌            |

Hai tính chất đáng chú ý:
  1. Vai và grant đọc từ DB MỖI REQUEST ⇒ duyệt / đổi vai / chặn có hiệu lực
     ngay ở request kế tiếp, không bắt đăng nhập lại (khác với nhét role vào JWT).
  2. Quyền KHÔNG BAO GIỜ xuất hiện trong thân endpoint — endpoint chỉ gọi
     `device_query` / `require_device_access` / `require_owner`.
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
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
# Vai được tạo/sửa/xóa kịch bản (kịch bản là của cả nhà, nên không cho kid/guest).
_CAN_EDIT_SCENES = ("owner", "adult")

_PENDING_MESSAGE = "Tài khoản chưa được thêm vào nhà. Nhờ chủ nhà thêm bạn ở Quản trị nhà → Thành viên."
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
        try:
            db.commit()
        except IntegrityError:
            # App mở lần đầu bắn vài request song song: request khác đã tạo
            # hàng này trước -> dùng hàng đó thay vì 500.
            db.rollback()
            member = db.query(MemberModel).filter(MemberModel.user_id == user.user_id).one()
            return member
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


def _visible_zone_ids(member: MemberModel):
    """
    Subquery id các khu kid/guest được thấy: khu được CẤP hoặc khu DÙNG CHUNG.
    Một chỗ duy nhất cho cả thiết bị, khu và lịch — thêm luật mới chỉ sửa ở đây.
    """
    granted = select(MemberZoneAccessModel.zone_id).where(MemberZoneAccessModel.user_id == member.user_id)
    return select(ZoneModel.id).where(or_(ZoneModel.id.in_(granted), ZoneModel.is_shared.is_(True)))


def device_query(db: Session, member: MemberModel):
    """
    Query các thiết bị mà `member` được phép thấy và điều khiển.

    owner/adult: tất cả, kể cả thiết bị chưa phân khu.
    kid/guest:   thiết bị thuộc khu được cấp hoặc khu dùng chung. Thiết bị
                 `zone_id IS NULL` tự rơi ra ngoài (IN không bao giờ khớp NULL),
                 đúng ý "hộp thư đến chỉ chủ nhà thấy", không cần case đặc biệt.
    """
    if sees_all_zones(member):
        return db.query(DeviceModel)
    return db.query(DeviceModel).filter(DeviceModel.zone_id.in_(_visible_zone_ids(member)))


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


def realtime_audience(db: Session, user_ids: set[str], device_id: str | None = None
                      ) -> tuple[set[str], set[str]]:
    """
    Ai trong `user_ids` (đang giữ kết nối /ws) được nhận sự kiện của `device_id`.

    Trả `(allowed, revoked)`:
      - revoked: không còn là thành viên ACTIVE (bị chặn / về chờ duyệt / bị
        xóa) ⇒ kết nối của họ phải bị ngắt, không chỉ bỏ qua.
      - allowed: active VÀ thiết bị nằm trong `device_query` của họ — đúng luật
        với GET /api/devices. `device_id` None = chỉ kiểm trạng thái thành viên.

    Đọc DB MỖI lần phát (như mọi request) ⇒ đổi khu / đổi vai / chặn có hiệu
    lực ngay sự kiện kế tiếp, không phải chờ app kết nối lại.
    """
    allowed: set[str] = set()
    revoked: set[str] = set()
    if not user_ids:
        return allowed, revoked
    members = {
        m.user_id: m
        for m in db.query(MemberModel).filter(MemberModel.user_id.in_(list(user_ids))).all()
    }
    for uid in user_ids:
        member = members.get(uid)
        if member is None or member.status != "active":
            revoked.add(uid)
            continue
        if device_id is None:
            allowed.add(uid)
            continue
        visible = (
            device_query(db, member)
            .filter(DeviceModel.id == device_id)
            .with_entities(DeviceModel.id)
            .first()
        )
        if visible is not None:
            allowed.add(uid)
    return allowed, revoked


def accessible_zones(db: Session, member: MemberModel) -> list[ZoneModel]:
    """Danh sách khu vực member được thấy, theo thứ tự hiển thị."""
    if sees_all_zones(member):
        return db.query(ZoneModel).order_by(ZoneModel.sort_order, ZoneModel.name).all()
    return (
        db.query(ZoneModel)
        .filter(ZoneModel.id.in_(_visible_zone_ids(member)))
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
        .filter(DeviceModel.zone_id.in_(_visible_zone_ids(member)))
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


def scheduler_target_device(db: Session, device_id: str) -> DeviceModel | None:
    """
    Luật quyền của BỘ HẸN GIỜ khi bắn lịch (vòng lặp trong FastAPI hoặc worker
    tại nhà — tác nhân HỆ THỐNG, không thay mặt ai).

    Lịch là của CẢ NHÀ: quyền đã kiểm lúc TẠO/SỬA lịch (`require_can_schedule`
    + `require_device_access`, đổi device_id phải có quyền thiết bị MỚI). Lúc
    bắn KHÔNG lọc theo người tạo — kid tạo lịch rồi bị thu quyền khu thì lịch
    vẫn là lịch của nhà, chủ nhà xóa ở tab Hẹn giờ nếu muốn.

    Điều kiện duy nhất: thiết bị CÒN trong bảng `devices`. Trả hàng thiết bị để
    người gọi lấy HÃNG từ DB (không tin `schedules.brand`) và chuẩn hóa hành
    động theo LOẠI (`normalize_action`). None = không được bắn.
    """
    if not device_id:
        return None
    return db.query(DeviceModel).filter(DeviceModel.id == device_id).first()


def require_scene_write(member: MemberModel) -> None:
    """Tạo/sửa/xóa kịch bản: chỉ owner/adult. Chạy thì ai cũng được (lọc theo thiết bị)."""
    if member.role not in _CAN_EDIT_SCENES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Chỉ chủ nhà hoặc người lớn mới tạo/sửa được kịch bản."
        )


# =========================================================
# Serialize
# =========================================================
def member_to_dict(member: MemberModel, zone_ids: list[int] | None = None) -> dict:
    data = {
        "user_id": member.user_id,
        "email": member.email,
        "display_name": member.display_name,
        "avatar_color": member.avatar_color,
        "role": member.role,
        "status": member.status,
        "can_admin": member.role in _ADMIN_ROLES,
        "can_schedule": member.role in _CAN_SCHEDULE_ROLES,
        "can_edit_scenes": member.role in _CAN_EDIT_SCENES,
        "sees_all_zones": sees_all_zones(member),
    }
    if zone_ids is not None:
        data["zone_ids"] = zone_ids
    return data


# ---------------------------------------------------------
# Thứ tự thiết bị trên Dashboard (members.sort_order)
# ---------------------------------------------------------
# Giới hạn chống payload rác; nhà thật chỉ có vài chục thiết bị.
DEVICE_ORDER_MAX_ITEMS = 500
DEVICE_ORDER_MAX_ID_LEN = 128


def _visible_device_ids(db: Session, member: MemberModel) -> set[str]:
    return {row[0] for row in device_query(db, member).with_entities(DeviceModel.id).all()}


def _dedupe_visible(ids, visible: set[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if isinstance(i, str) and i in visible and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def device_order_of(db: Session, member: MemberModel) -> list[str]:
    """
    Thứ tự đã lưu, CHỈ gồm thiết bị `member` đang được thấy. Lọc lúc ĐỌC chứ
    không ghi lại DB: thiết bị bị xóa / mất quyền tự biến mất, được cấp lại thì
    vị trí cũ quay về. Giá trị hỏng (không phải list) -> [] = thứ tự mặc định.
    """
    raw = member.sort_order
    if not isinstance(raw, list) or not raw:
        return []
    return _dedupe_visible(raw, _visible_device_ids(db, member))


def sanitize_device_order(db: Session, member: MemberModel, ids: list[str]) -> list[str]:
    """
    Làm sạch danh sách client gửi lên: khử trùng (giữ lần xuất hiện đầu), bỏ
    id không tồn tại hoặc ngoài quyền. Bỏ âm thầm thay vì 400: thiết bị có thể
    vừa bị xóa giữa lúc kéo-thả và lúc lưu — 400 thì app sẽ thử lại mãi.
    """
    return _dedupe_visible(ids, _visible_device_ids(db, member))


def zone_ids_of(db: Session, user_id: str) -> list[int]:
    rows = (
        db.query(MemberZoneAccessModel.zone_id)
        .filter(MemberZoneAccessModel.user_id == user_id)
        .all()
    )
    return sorted(r[0] for r in rows)
