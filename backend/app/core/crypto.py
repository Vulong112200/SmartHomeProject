# backend/app/core/crypto.py
"""
Mã hóa credential nhà cung cấp (VeSync email/pass) trước khi lưu DB.
Dùng Fernet (đối xứng) với khóa FERNET_KEY trong env. Cần lưu password để
re-login VeSync sau khi server restart — bắt buộc mã hóa at rest.
"""
import os
import json
from functools import lru_cache
from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.getenv("FERNET_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "Thiếu FERNET_KEY. Sinh bằng: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def encrypt_json(data: dict) -> str:
    """Mã hóa 1 dict -> token chuỗi để lưu vào cột credentials_encrypted."""
    raw = json.dumps(data, separators=(",", ":")).encode()
    return _fernet().encrypt(raw).decode()


def decrypt_json(token: str) -> dict:
    """Giải mã token -> dict. Ném ValueError nếu token hỏng/không hợp lệ."""
    if not token:
        return {}
    try:
        raw = _fernet().decrypt(token.encode())
        return json.loads(raw.decode())
    except Exception as e:
        raise ValueError(f"Không giải mã được credential: {e}")
