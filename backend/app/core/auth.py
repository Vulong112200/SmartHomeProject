# backend/app/core/auth.py
"""
Xác thực người dùng qua JWT của Supabase.

Hai kiểu ký token, chọn theo `alg` trong header của token:
  - ES256 / RS256 (JWT Signing Keys — mặc định của project Supabase MỚI): verify
    bằng khóa công khai lấy từ JWKS `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`.
    Cần SUPABASE_URL. Không cần secret nào.
  - HS256 (legacy JWT secret — project cũ): verify bằng SUPABASE_JWT_SECRET.
Project của nhà dùng ES256: chỉ verify HS256 thì đăng nhập xong mọi request 401.

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
    return not _can_verify_supabase()


def _supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")


def _can_verify_supabase() -> bool:
    """Có cách verify token Supabase nào không (JWKS qua SUPABASE_URL, hoặc secret HS256)."""
    return bool(_supabase_url() or os.getenv("SUPABASE_JWT_SECRET", "").strip())


def auth_status() -> tuple[bool, str]:
    """(có bật xác thực không, lý do) — để lifespan log rõ lúc khởi động."""
    raw = os.getenv("AUTH_DISABLED")
    if raw is not None and raw.strip() != "":
        explicit = raw.strip().lower() in ("1", "true", "yes")
        return (not explicit, f"AUTH_DISABLED={raw.strip()} (đặt tường minh)")
    if _supabase_url():
        return (True, "có SUPABASE_URL (verify JWKS)")
    if os.getenv("SUPABASE_JWT_SECRET", "").strip():
        return (True, "có SUPABASE_JWT_SECRET (verify HS256)")
    return (False, "thiếu SUPABASE_URL / SUPABASE_JWT_SECRET")


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


# =========================================================
# Token Supabase
# =========================================================
_jwks_clients: dict[str, "jwt.PyJWKClient"] = {}


def _jwks_client(url: str) -> "jwt.PyJWKClient":
    """1 client/URL, cache khóa: chỉ tải JWKS lần đầu và khi gặp `kid` lạ (xoay khóa)."""
    if url not in _jwks_clients:
        _jwks_clients[url] = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=10)
    return _jwks_clients[url]


def _decode_supabase_token(token: str) -> dict:
    """Verify access token Supabase theo `alg` của nó. Sai -> HTTP 401."""
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Token không hợp lệ: {e}")

    try:
        if alg in ("ES256", "RS256"):
            base = _supabase_url()
            if not base:
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "Server chưa cấu hình SUPABASE_URL (cần để verify token ES256).",
                )
            key = _jwks_client(f"{base}/auth/v1/.well-known/jwks.json").get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=[alg], audience="authenticated",
                              issuer=f"{base}/auth/v1")
        if alg == "HS256":
            secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
            if not secret:
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "Server chưa cấu hình SUPABASE_JWT_SECRET (cần để verify token HS256).",
                )
            return jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
    except (jwt.PyJWTError, jwt.PyJWKClientError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Token không hợp lệ: {e}")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Thuật toán token không hỗ trợ: {alg}")


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

    # App-token cấp lúc xác thực còn TẮT mang danh tính chủ nhà giả (DEV_USER_ID +
    # email admin) và sống 10 năm. Không chặn thì sau khi bật xác thực, widget/
    # shortcut của mọi máy (kể cả người pending/bị chặn — họ không xin được token
    # mới để ghi đè) vẫn có toàn quyền chủ nhà. Từ chối => app mở lần kế tự xin
    # token đúng người.
    if payload is not None and payload.get("sub") == DEV_USER_ID:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "App-token cũ (cấp lúc xác thực tắt) — mở app để xin token mới.",
        )

    if payload is None:
        payload = _decode_supabase_token(creds.credentials)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token thiếu 'sub'.")
    email = (payload.get("email") or "").lower()
    return CurrentUser(user_id=user_id, email=email, is_admin=email in admin_emails())
