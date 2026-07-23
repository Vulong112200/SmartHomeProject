# backend/app/core/auth.py
"""
Xác thực người dùng qua JWT của Supabase (HS256, legacy JWT secret).

Backend chỉ verify token và trích user_id/email; toàn bộ đăng nhập/đăng ký do
Supabase Auth lo ở phía app. is_admin xác định qua ADMIN_EMAILS (env).

Local dev: đặt AUTH_DISABLED=1 để bỏ verify (trả user giả cố định) — tiện test
offline không cần Supabase. TUYỆT ĐỐI không bật trên production.
"""
import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

# User giả khi AUTH_DISABLED=1 (dev). user_id cố định để dữ liệu ổn định giữa các lần chạy.
_DEV_USER_ID = "00000000-0000-0000-0000-000000000000"


@dataclass
class CurrentUser:
    user_id: str
    email: str
    is_admin: bool


def _admin_emails() -> set[str]:
    raw = os.getenv("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _auth_disabled() -> bool:
    return os.getenv("AUTH_DISABLED", "0").strip() in ("1", "true", "True")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Dependency: verify Bearer JWT của Supabase -> CurrentUser. 401 nếu thiếu/sai."""
    if _auth_disabled():
        dev_email = (os.getenv("ADMIN_EMAILS", "").split(",")[0] or "dev@local").strip()
        return CurrentUser(user_id=_DEV_USER_ID, email=dev_email, is_admin=True)

    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Thiếu token đăng nhập.")

    secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    if not secret:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "Server chưa cấu hình SUPABASE_JWT_SECRET.")
    try:
        payload = jwt.decode(
            creds.credentials, secret, algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Token không hợp lệ: {e}")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token thiếu 'sub'.")
    email = (payload.get("email") or "").lower()
    return CurrentUser(user_id=user_id, email=email, is_admin=email in _admin_emails())


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency chỉ cho phép admin."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Yêu cầu quyền admin.")
    return user
