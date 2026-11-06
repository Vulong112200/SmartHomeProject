"""Cấu hình worker — CHỈ từ biến môi trường (không hardcode credential)."""
import os
from dataclasses import dataclass
from typing import Optional

from app.core.database import normalize_database_url

TICK_MIN, TICK_MAX, TICK_DEFAULT = 5, 55, 30


class ConfigError(Exception):
    """Cấu hình sai — worker không được chạy (thoát mã 2)."""


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str
    tick_seconds: int
    log_file: Optional[str]
    log_level: str

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def load_config() -> WorkerConfig:
    # WORKER_DATABASE_URL cho phép worker dùng role DB quyền hẹp khác với
    # DATABASE_URL của backend (xem README — "Quyền database tối thiểu").
    raw = (os.getenv("WORKER_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        raise ConfigError(
            "Thiếu WORKER_DATABASE_URL / DATABASE_URL. Worker phải trỏ vào CÙNG Postgres "
            "(Supabase) với backend — không đặt thì database.py sẽ rơi về SQLite local, "
            "worker đọc một DB rỗng và không bắn lịch nào mà không báo lỗi."
        )
    url = normalize_database_url(raw)
    if url.startswith("sqlite") and not _truthy("WORKER_ALLOW_SQLITE"):
        raise ConfigError(
            "DATABASE_URL đang trỏ SQLite. Worker chỉ có ý nghĩa với Postgres dùng chung với "
            "backend. Dev/test: đặt WORKER_ALLOW_SQLITE=1."
        )

    tick_raw = os.getenv("WORKER_TICK_SECONDS", "").strip() or str(TICK_DEFAULT)
    try:
        tick = int(tick_raw)
    except ValueError:
        raise ConfigError(f"WORKER_TICK_SECONDS={tick_raw!r} không phải số nguyên.")
    # Cửa sổ kích hoạt là 120s: tick > 55s có thể chỉ rơi vào cửa sổ 1 lần,
    # một tick lỗi mạng là lỡ hẹn.
    if not TICK_MIN <= tick <= TICK_MAX:
        raise ConfigError(f"WORKER_TICK_SECONDS phải trong khoảng {TICK_MIN}–{TICK_MAX}.")

    return WorkerConfig(
        database_url=url,
        tick_seconds=tick,
        log_file=os.getenv("WORKER_LOG_FILE", "").strip() or None,
        log_level=(os.getenv("WORKER_LOG_LEVEL", "").strip() or "INFO").upper(),
    )
