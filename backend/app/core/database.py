# backend/app/core/database.py
import logging
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# =========================================================
# Chọn DB theo môi trường
#   - DATABASE_URL đặt sẵn (Supabase Postgres) -> dùng Postgres.
#   - Không đặt -> SQLite local như cũ (dev/test offline vẫn chạy y nguyên).
# Lý do cần Postgres: ổ đĩa Render free là ephemeral, container dựng lại mỗi
# lần deploy nên smarthome.db bị ghi đè -> lịch hẹn của người dùng bay sạch.
# =========================================================
def normalize_database_url(raw: str) -> str:
    """
    Supabase/Heroku in connection string dạng "postgres://", SQLAlchemy 2.x chỉ
    nhận "postgresql://". Không sửa ở đây thì lỗi khó đoán: NoSuchModuleError.
    Rỗng -> SQLite local.
    """
    url = (raw or "").strip() or "sqlite:///./smarthome.db"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def make_engine(url: str):
    """Dựng engine với tham số pool hợp với từng loại DB."""
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # Postgres qua Supabase pooler: pre_ping loại bỏ kết nối đã chết sau khi
    # idle (Render free ngủ thường xuyên), recycle vì pooler cắt kết nối cũ.
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=5,
    )


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", ""))
IS_SQLITE = DATABASE_URL.startswith("sqlite")
engine = make_engine(DATABASE_URL)

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


# =========================================================
# Schema: tự lành + verify được
# =========================================================
# 3 thiết bị đang chạy thật. Seed để một Postgres rỗng vẫn phục vụ được ngay
# mà không cần chạy tay supabase_schema.sql. GIỮ NGUYÊN id — shortcut đã pin
# và slot Home Widget trên điện thoại lưu theo brand+id, đổi id là hỏng cả hai.
_SEED_DEVICES = [
    ("a32aae46a67dbe52860pza", "Cửa cuốn", "tuya", "curtain"),
    ("vsaq325492d4dce9e0f8eb348bb3be41", "Lọc không khí Core 300S", "vesync", "purifier"),
    ("a32e6ab42d076b8bb5bbrh", "Máy cho mèo ăn tự động", "rojeco", "feeder"),
]

# Khu mặc định cho lần chạy đầu. Chủ nhà chia phòng thật sau ở tab Khu vực.
_DEFAULT_ZONE_NAME = "Nhà"

# Cột thêm sau khi bảng đã tồn tại. create_all KHÔNG bao giờ ALTER bảng cũ,
# nên phải tự thêm ở đây. Kiểu khác nhau giữa 2 dialect: Boolean của SQLite là
# INTEGER, của Postgres là BOOLEAN — dùng chung một DDL sẽ lỗi trên Postgres.
_WANTED_COLUMNS = {
    "schedules": {
        "end_time": {"sqlite": "TEXT", "postgresql": "TEXT"},
        "end_action_type": {"sqlite": "TEXT", "postgresql": "TEXT"},
        "end_action_value": {"sqlite": "TEXT", "postgresql": "TEXT"},
        "last_end_fired_date": {"sqlite": "TEXT", "postgresql": "TEXT"},
        "one_shot": {
            "sqlite": "INTEGER DEFAULT 0",
            "postgresql": "BOOLEAN DEFAULT FALSE",
        },
        # Phase 1b — chỉ để audit và chặn kid sửa lịch người khác.
        "created_by": {"sqlite": "TEXT", "postgresql": "TEXT"},
    },
    "devices": {
        # Phase 1b — NULL = "hộp thư đến", chỉ owner/adult thấy.
        # Không đặt FK trong ALTER: SQLite không thêm được FK sau khi tạo bảng,
        # và bảng mới thì create_all đã gắn FK đầy đủ rồi.
        "zone_id": {"sqlite": "INTEGER", "postgresql": "INTEGER"},
        "category": {"sqlite": "TEXT", "postgresql": "TEXT"},
    },
    "members": {
        # Đợt 2 — màu avatar ở màn Hồ sơ.
        "avatar_color": {"sqlite": "TEXT", "postgresql": "TEXT"},
    },
}

# verify_schema kiểm đúng những cột mà code thật sự đọc/ghi.
_REQUIRED_SCHEMA = {
    "devices": {"id", "name", "brand", "is_active", "zone_id", "category"},
    "schedules": {
        "id", "name", "brand", "device_id", "action_type", "action_value",
        "time", "days", "enabled", "last_fired_date", "end_time",
        "end_action_type", "end_action_value", "last_end_fired_date", "one_shot",
        "created_by",
    },
    "members": {"user_id", "email", "display_name", "role", "status", "avatar_color"},
    "zones": {"id", "name", "sort_order"},
    "member_zone_access": {"user_id", "zone_id"},
}


def run_startup_migrations(bind=None) -> None:
    """
    Thêm cột còn thiếu vào bảng đã tồn tại. Idempotent — chỉ thêm cột chưa có,
    không bao giờ DROP (không hoàn tác được, mà hàm này chạy mỗi lần boot).
    Chạy cho cả SQLite lẫn Postgres.
    """
    bind = bind if bind is not None else engine
    dialect = bind.dialect.name  # "sqlite" | "postgresql"
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    for table, wanted in _WANTED_COLUMNS.items():
        if table not in tables:
            continue  # create_all sẽ tạo bảng với đủ cột, khỏi migrate
        existing = {col["name"] for col in inspector.get_columns(table)}
        missing = {n: t for n, t in wanted.items() if n not in existing}
        if not missing:
            continue
        with bind.begin() as conn:
            for name, types in missing.items():
                ddl = types.get(dialect, types["sqlite"])
                # SQLite không có ADD COLUMN IF NOT EXISTS; đã lọc `missing` ở trên.
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                logger.info("Đã thêm cột %s.%s (%s)", table, name, ddl)


def enable_rls(bind=None) -> None:
    """
    Bật Row Level Security cho bảng do create_all tạo (chỉ Postgres/Supabase).

    Vì sao cần: Supabase grant sẵn quyền cho role `anon`/`authenticated` trên
    schema `public`, mà anon key thì nằm ngay trong APK. Bảng mới tạo bằng
    create_all KHÔNG có RLS => ai rút được key từ APK là đọc/ghi được cả bảng.

    Bật RLS mà KHÔNG viết policy = deny-all cho anon/authenticated. Backend nối
    bằng role `postgres` nên bỏ qua RLS hoàn toàn, vẫn chạy bình thường.
    """
    bind = bind if bind is not None else engine
    if bind.dialect.name != "postgresql":
        return
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    with bind.begin() as conn:
        for table in _REQUIRED_SCHEMA:
            if table not in tables:
                continue
            conn.execute(text(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY"))
    logger.info("Đã bật RLS (deny-all cho anon/authenticated) trên %s", list(_REQUIRED_SCHEMA))


def seed_defaults(bind=None) -> None:
    """
    Nạp dữ liệu tối thiểu để nhà chạy được ngay:
      - 3 thiết bị đang dùng, nếu bảng `devices` rỗng;
      - một khu vực 'Nhà', nếu bảng `zones` rỗng, rồi gán mọi thiết bị chưa
        phân khu vào đó.

    Cả hai bước chỉ chạy khi bảng tương ứng RỖNG, nên không bao giờ ghi đè
    dữ liệu người dùng đã sửa (đổi tên thiết bị, xóa bớt, chia phòng lại).
    """
    bind = bind if bind is not None else engine
    with bind.begin() as conn:
        if not conn.execute(text("SELECT COUNT(*) FROM devices")).scalar():
            for device_id, name, brand, category in _SEED_DEVICES:
                conn.execute(
                    text(
                        "INSERT INTO devices (id, name, brand, is_active, category) "
                        "VALUES (:id, :name, :brand, :active, :category)"
                    ),
                    {"id": device_id, "name": name, "brand": brand, "active": True,
                     "category": category},
                )
            logger.info("Đã seed %d thiết bị mặc định.", len(_SEED_DEVICES))

        # Khu mặc định: nếu không có, mọi thiết bị cũ sẽ nằm ở "hộp thư đến"
        # (zone_id IS NULL) và kid/guest không thể được cấp quyền cho chúng.
        if not conn.execute(text("SELECT COUNT(*) FROM zones")).scalar():
            conn.execute(
                text("INSERT INTO zones (name, sort_order) VALUES (:name, 0)"),
                {"name": _DEFAULT_ZONE_NAME},
            )
            zone_id = conn.execute(
                text("SELECT id FROM zones WHERE name = :name"),
                {"name": _DEFAULT_ZONE_NAME},
            ).scalar()
            conn.execute(
                text("UPDATE devices SET zone_id = :zid WHERE zone_id IS NULL"),
                {"zid": zone_id},
            )
            logger.info("Đã tạo khu mặc định '%s' và gán thiết bị chưa phân khu vào đó.",
                        _DEFAULT_ZONE_NAME)


def verify_schema(bind=None) -> None:
    """
    Kiểm schema khớp với những gì code đọc/ghi. Raise nếu thiếu — lifespan bắt
    exception này và cho app boot ở chế độ degraded, /health báo db:false.
    Không có bước này thì schema lệch chỉ lộ ra lúc request đầu tiên lỗi 500.
    """
    bind = bind if bind is not None else engine
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    problems = []
    for table, required in _REQUIRED_SCHEMA.items():
        if table not in tables:
            problems.append(f"thiếu bảng '{table}'")
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        missing = required - existing
        if missing:
            problems.append(f"bảng '{table}' thiếu cột: {sorted(missing)}")

    if problems:
        raise RuntimeError(
            "Schema DB không khớp với code — "
            + "; ".join(problems)
            + f". (DB đang dùng: {bind.dialect.name})"
        )


def init_db(bind=None) -> None:
    """
    Khởi tạo schema. Gọi từ lifespan của main.py, KHÔNG gọi ở tầng import:
    exception lúc import làm uvicorn chết với "Error loading ASGI app", không
    route nào chạy, kể cả /health.

    create_all có checkfirst=True nên là no-op khi supabase_schema.sql đã apply.

    `bind` chỉ dùng cho test (trỏ vào DB tạm). Production gọi không tham số.
    """
    bind = bind if bind is not None else engine

    # import để models đăng ký vào Base.metadata trước khi create_all
    from app.models import device, member, schedule, zone  # noqa: F401

    Base.metadata.create_all(bind=bind)
    run_startup_migrations(bind)
    # verify TRƯỚC seed: nếu schema lệch thì seed sẽ ném OperationalError thô
    # (stack trace SQLAlchemy), che mất thông báo nói rõ bảng/cột nào thiếu.
    verify_schema(bind)
    enable_rls(bind)
    seed_defaults(bind)
