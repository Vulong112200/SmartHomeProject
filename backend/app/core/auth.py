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
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

# Token dài hạn do CHÍNH backend cấp, dành cho isolate nền của Android
# (Home Widget + shortcut đã pin). Xem issue_app_token() bên dưới.
APP_TOKEN_ISSUER = "smarthome-app"
APP_TOKEN_DAYS = 3650

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


# =========================================================
# Token dài hạn cho isolate nền (Home Widget + shortcut)
# =========================================================
def app_token_secret() -> str:
    """
    Secret ký token dài hạn. Không đặt riêng thì dùng SUPABASE_JWT_SECRET —
    một biến ít hơn phải nhớ, và thu hồi vẫn làm được bằng cách đổi nó.
    """
    return (
        os.getenv("APP_TOKEN_SECRET", "").strip()
        or os.getenv("SUPABASE_JWT_SECRET", "").strip()
    )


def issue_app_token(user_id: str, email: str) -> str:
    """
    Cấp token dài hạn cho app, dùng ở isolate nền.

    Vì sao cần: `widgetBackgroundCallback` và shortcut handler chạy ở
    **isolate riêng**, nơi `Supabase.instance` chưa từng được khởi tạo ⇒ không
    lấy được access token ⇒ Home Widget hiện "Không rõ" và nút bấm im lặng
    không làm gì. Re-init Supabase trong isolate thì hai isolate refresh song
    song, mà Supabase **xoay vòng refresh token** ⇒ isolate này vô hiệu hóa
    token của isolate kia, cả nhà bị đăng xuất ngẫu nhiên. Cache access token
    1 giờ thì hỏng mỗi khi bấm widget sau 1 giờ — tức là hầu như luôn.

    Thu hồi = đổi APP_TOKEN_SECRET (hoặc SUPABASE_JWT_SECRET).
    """
    secret = app_token_secret()
    if not secret:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Server chưa cấu hình APP_TOKEN_SECRET / SUPABASE_JWT_SECRET.",
        )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iss": APP_TOKEN_ISSUER,
        "iat": now,
        "exp": now + timedelta(days=APP_TOKEN_DAYS),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _decode_app_token(token: str) -> dict | None:
    """Thử đọc như token do backend cấp. Không phải của mình thì trả None."""
    secret = app_token_secret()
    if not secret:
        return None
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], issuer=APP_TOKEN_ISSUER)
    except jwt.PyJWTError:
        return None


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Dependency: verify Bearer JWT (Supabase hoặc app-token) -> CurrentUser."""
    if auth_disabled():
        dev_email = (os.getenv("ADMIN_EMAILS", "").split(",")[0] or DEV_EMAIL).strip()
        return CurrentUser(user_id=DEV_USER_ID, email=dev_email.lower(), is_admin=True)

    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Thiếu token đăng nhập.")

    # Thử app-token trước: nó có `iss` riêng nên không thể nhầm với token
    # Supabase, và đây là đường đi của Home Widget / shortcut.
    payload = _decode_app_token(creds.credentials)

    if payload is None:
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
