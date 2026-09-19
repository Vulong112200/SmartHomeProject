# backend/app/core/auth.py
"""
Xác thực người dùng qua JWT của Supabase (HS256, legacy JWT secret).

File này CỐ TÌNH sạch model và sạch DB: nó chỉ verify token và trích
user_id/email. Mọi thứ liên quan tới vai/khu vực/quyền nằm ở core/household.py.

Local dev: đặt AUTH_DISABLED=1 để bỏ verify (trả user giả cố định) — tiện test
offline không cần Supabase. TUYỆT ĐỐI không bật trên production.
"""
import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

# User giả khi AUTH_DISABLED=1. user_id cố định để dữ liệu ổn định giữa các lần chạy.
DEV_USER_ID = "00000000-0000-0000-0000-000000000000"
DEV_EMAIL = "dev@local"


@dataclass
class CurrentUser:
    user_id: str
    email: str
    # Email nằm trong ADMIN_EMAILS. Đây là cứu hộ cấp env: chủ nhà không bao giờ
    # tự khóa mình khỏi nhà mình, kể cả khi lỡ tay đổi vai trong DB.
    is_admin: bool


def admin_emails() -> set[str]:
    raw = os.getenv("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def auth_disabled() -> bool:
    """
    Có bỏ qua xác thực không.

    Thứ tự quyết định:
      1. AUTH_DISABLED đặt tường minh -> theo đúng giá trị đó. Đặt "0" là ép
         BẬT xác thực kể cả khi thiếu secret (fail closed, cho người vận hành
         muốn chắc chắn).
      2. Không đặt -> suy từ SUPABASE_JWT_SECRET. Thiếu secret thì backend
         KHÔNG THỂ verify token: bật xác thực chỉ làm mọi request 401 và app
         của cả nhà chết. Nên mặc định chạy mở, kèm cảnh báo mỗi lần boot.

    Vì sao cần suy: service Render được tạo tay trên dashboard nên KHÔNG đọc
    render.yaml — quên set biến ở dashboard là đủ để làm sập app đang phục vụ
    thật. Phase 2 đặt SUPABASE_JWT_SECRET, và xác thực tự bật lên.
    """
    raw = os.getenv("AUTH_DISABLED")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in ("1", "true", "yes")
    return not os.getenv("SUPABASE_JWT_SECRET", "").strip()


def auth_status() -> tuple[bool, str]:
    """(có bật xác thực không, lý do) — để lifespan log rõ lúc khởi động."""
    raw = os.getenv("AUTH_DISABLED")
    if raw is not None and raw.strip() != "":
        explicit = raw.strip().lower() in ("1", "true", "yes")
        return (not explicit, f"AUTH_DISABLED={raw.strip()} (đặt tường minh)")
    if os.getenv("SUPABASE_JWT_SECRET", "").strip():
        return (True, "có SUPABASE_JWT_SECRET")
    return (False, "thiếu SUPABASE_JWT_SECRET")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Dependency: verify Bearer JWT của Supabase -> CurrentUser. 401 nếu thiếu/sai."""
    if auth_disabled():
        dev_email = (os.getenv("ADMIN_EMAILS", "").split(",")[0] or DEV_EMAIL).strip()
        return CurrentUser(user_id=DEV_USER_ID, email=dev_email.lower(), is_admin=True)

    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Thiếu token đăng nhập.")

    secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Server chưa cấu hình SUPABASE_JWT_SECRET.",
        )
    try:
        payload = jwt.decode(
            creds.credentials,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Token không hợp lệ: {e}")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token thiếu 'sub'.")
    email = (payload.get("email") or "").lower()
    return CurrentUser(user_id=user_id, email=email, is_admin=email in admin_emails())
