"""
Verify token Supabase ES256 (JWT Signing Keys — kiểu project mới) qua JWKS,
song song với HS256 cũ. Khóa EC tự sinh, JWKS client bị thay bằng bản giả —
không gọi mạng.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import auth

URL = "https://abc.supabase.co"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("APP_TOKEN_SECRET", "app-secret-for-tests-0123456789abcdef")
    monkeypatch.setenv("ADMIN_EMAILS", "chu@x.test")
    key = ec.generate_private_key(ec.SECP256R1())
    fetched = []

    class FakeJwks:
        def get_signing_key_from_jwt(self, token):
            fetched.append(jwt.get_unverified_header(token)["kid"])
            return SimpleNamespace(key=key.public_key())

    monkeypatch.setattr(auth, "_jwks_client", lambda url: fetched.append(url) or FakeJwks())
    return SimpleNamespace(key=key, fetched=fetched, monkeypatch=monkeypatch)


def _es256(env, **over):
    now = int(time.time())
    claims = {"sub": "u-1", "email": "Chu@x.test", "aud": "authenticated",
              "iss": f"{URL}/auth/v1", "iat": now, "exp": now + 3600, **over}
    return jwt.encode(claims, env.key, algorithm="ES256", headers={"kid": "k1"})


def _user(token):
    return auth.get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))


def test_token_es256_hop_le_duoc_chap_nhan(env):
    u = _user(_es256(env))
    assert (u.user_id, u.email, u.is_admin) == ("u-1", "chu@x.test", True)
    assert f"{URL}/auth/v1/.well-known/jwks.json" in env.fetched


@pytest.mark.parametrize("over", [
    {"aud": "anon"},                                  # không phải token đăng nhập
    {"iss": "https://khac.supabase.co/auth/v1"},     # project khác
    {"exp": int(time.time()) - 10},                   # hết hạn
])
def test_token_es256_sai_bi_401(env, over):
    with pytest.raises(HTTPException) as e:
        _user(_es256(env, **over))
    assert e.value.status_code == 401


def test_token_ky_bang_khoa_khac_bi_401(env):
    other = ec.generate_private_key(ec.SECP256R1())
    now = int(time.time())
    token = jwt.encode({"sub": "x", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": now + 60},
                       other, algorithm="ES256", headers={"kid": "k1"})
    with pytest.raises(HTTPException) as e:
        _user(token)
    assert e.value.status_code == 401


def test_hs256_cu_van_chay_neu_co_secret(env):
    env.monkeypatch.setenv("SUPABASE_JWT_SECRET", "legacy-secret-0123456789abcdef0123")
    token = jwt.encode({"sub": "u-2", "email": "a@x.test", "aud": "authenticated",
                        "exp": int(time.time()) + 60}, "legacy-secret-0123456789abcdef0123", algorithm="HS256")
    assert _user(token).user_id == "u-2"


def test_app_token_van_dung_cho_widget(env):
    token = auth.issue_app_token("u-3", "w@x.test")
    assert _user(token).user_id == "u-3"


def test_chi_co_supabase_url_la_xac_thuc_tu_bat(env):
    assert auth.auth_disabled() is False
    env.monkeypatch.delenv("SUPABASE_URL")
    assert auth.auth_disabled() is True  # không có cách verify -> chạy mở như trước


def test_thuat_toan_none_bi_tu_choi(env):
    token = jwt.encode({"sub": "hacker", "aud": "authenticated"}, None, algorithm="none")
    with pytest.raises(HTTPException) as e:
        _user(token)
    assert e.value.status_code == 401
