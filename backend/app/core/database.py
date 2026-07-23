# backend/app/core/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# =========================================================
# Chọn DB theo môi trường:
#   - DATABASE_URL đặt sẵn (Supabase Postgres) -> dùng Postgres.
#   - Không đặt -> fallback SQLite local (tiện dev/test offline).
# =========================================================
DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or "sqlite:///./smarthome.db"
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    # Postgres (Supabase pooler): pre_ping tránh kết nối chết sau khi idle,
    # recycle định kỳ vì pooler có thể cắt kết nối cũ.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=5,
    )

# Tạo một "nhà máy" sản xuất các phiên làm việc (Session) với DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class: Mọi bảng dữ liệu (Models) sau này sẽ kế thừa từ class này
Base = declarative_base()

# Hàm hỗ trợ lấy kết nối DB cho các API
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Khởi tạo schema.
      - SQLite (local): create_all + ALTER thêm cột thiếu (bảng cũ).
      - Postgres (Supabase): KHÔNG create_all — schema quản lý qua
        backend/docs/supabase_schema.sql. Chỉ import models để đăng ký metadata.
    """
    # import để models đăng ký vào Base.metadata
    from app.models import device, schedule, vendor_account  # noqa: F401

    if IS_SQLITE:
        Base.metadata.create_all(bind=engine)
        run_startup_migrations(engine)


def run_startup_migrations(engine) -> None:
    """
    Migration nhẹ cho SQLite: create_all KHÔNG thêm cột vào bảng đã tồn tại,
    nên các cột mới phải ALTER TABLE thủ công ở đây. Idempotent — chỉ thêm cột thiếu.
    (Không chạy cho Postgres — Supabase dùng file SQL riêng.)
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    def _add_missing(table: str, wanted: dict[str, str]) -> None:
        if table not in tables:
            return
        existing = {col["name"] for col in inspector.get_columns(table)}
        missing = {n: ddl for n, ddl in wanted.items() if n not in existing}
        if not missing:
            return
        with engine.begin() as conn:
            for name, ddl in missing.items():
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

    # schedules: cột lịch khoảng (bản cũ) + user_id (multi-user)
    _add_missing("schedules", {
        "end_time": "TEXT",
        "end_action_type": "TEXT",
        "end_action_value": "TEXT",
        "last_end_fired_date": "TEXT",
        "one_shot": "INTEGER DEFAULT 0",
        "user_id": "TEXT DEFAULT ''",
    })
    # devices: cột multi-user
    _add_missing("devices", {
        "user_id": "TEXT DEFAULT ''",
        "category": "TEXT",
        "sort_order": "INTEGER DEFAULT 0",
        "created_at": "TEXT",
    })
