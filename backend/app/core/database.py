# backend/app/core/database.py
import logging
import os
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
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


# =========================================================
# Engine ASYNC (SQLAlchemy 2.0): asyncpg cho Postgres, aiosqlite cho SQLite
# =========================================================
# Supabase transaction pooler (cổng 6543) không giữ prepared statement giữa các
# transaction ⇒ asyncpg lỗi "prepared statement ... already exists". Session
# pooler (5432, đang dùng) và kết nối thẳng không bị.
_TRANSACTION_POOLER_PORT = 6543

# sslmode là tham số của libpq/psycopg2; asyncpg nhận `ssl` với cùng tập giá trị.
# Không đổi thì URL Supabase có `?sslmode=require` làm asyncpg.connect() ném
# TypeError ngay lúc kết nối đầu tiên.
_LIBPQ_ONLY_PARAMS = ("sslmode", "connect_timeout", "application_name")


def async_database_url(url) -> URL:
    """
    URL đồng bộ ("postgresql://", "sqlite:///") -> URL cho driver async.
    Driver ghi sẵn (vd "+psycopg2") bị thay: cả backend chỉ chạy một kiểu driver.
    Trả `URL` (không phải chuỗi) để mật khẩu có ký tự đặc biệt không bị escape sai.
    """
    u = make_url(url) if not isinstance(url, URL) else url
    backend = u.get_backend_name()
    if backend == "sqlite":
        return u.set(drivername="sqlite+aiosqlite")
    if backend != "postgresql":
        raise ValueError(f"DATABASE_URL không hỗ trợ: {backend}")
    query = {k: v for k, v in u.query.items() if k not in _LIBPQ_ONLY_PARAMS}
    return u.set(drivername="postgresql+asyncpg", query=query)


def async_connect_args(url, application_name: str = "smarthome-api") -> dict:
    """
    Tham số asyncpg.connect() suy từ URL gốc (đọc các tham số libpq đã gỡ khỏi URL).
    - timeout: kết nối không được >10s (mạng chập chờn thì lỗi nhanh, không treo).
    - command_timeout: 1 câu SQL treo (mất mạng giữa chừng) không giữ request mãi.
    - transaction pooler: tắt cache prepared statement + tên ngẫu nhiên.
    """
    u = make_url(url) if not isinstance(url, URL) else url
    if u.get_backend_name() == "sqlite":
        # busy timeout: request async chạy song song thật sự ⇒ có lúc chờ khóa ghi.
        return {"timeout": 30}
    q = u.query
    args: dict = {
        "timeout": float(q.get("connect_timeout") or 10),
        "command_timeout": 30,
        "server_settings": {"application_name": q.get("application_name") or application_name},
    }
    if q.get("sslmode"):
        args["ssl"] = q["sslmode"]
    if u.port == _TRANSACTION_POOLER_PORT:
        args["statement_cache_size"] = 0
        args["prepared_statement_cache_size"] = 0
        args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"
    return args


def make_async_engine(url, *, pool_size: int = 5, max_overflow: int = 5,
                      application_name: str = "smarthome-api"):
    """
    Engine async với pool hợp từng loại DB.
    Postgres: pool_pre_ping loại kết nối chết sau khi idle (Render free ngủ),
    recycle vì pooler cắt kết nối cũ, pool_timeout ngắn: hết kết nối thì báo lỗi
    sau 10s (→ 503) thay vì treo request 30s.
    """
    aurl = async_database_url(url)
    connect_args = async_connect_args(url, application_name)
    if aurl.get_backend_name() == "sqlite":
        return create_async_engine(aurl, connect_args=connect_args)
    return create_async_engine(
        aurl,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=10,
        connect_args=connect_args,
    )


def make_session_factory(bind) -> async_sessionmaker:
    """
    expire_on_commit=False: BẮT BUỘC với AsyncSession — đọc thuộc tính sau commit
    không được phát SQL ngầm (lazy load ngoài greenlet = MissingGreenlet). Hệ quả:
    object không tự làm mới sau commit; chỗ nào cần giá trị DB mới (sau UPDATE
    Core) phải đọc lại tường minh (`populate_existing=True` / `refresh`).
    """
    return async_sessionmaker(bind=bind, class_=AsyncSession, expire_on_commit=False, autoflush=False)


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", ""))
IS_SQLITE = DATABASE_URL.startswith("sqlite")
engine = make_engine(DATABASE_URL)

# Tạo một "nhà máy" sản xuất các phiên làm việc (Session) với DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Engine + session async. Tạo engine KHÔNG mở kết nối (lười) ⇒ import không
# bao giờ ném vì DB chết.
async_engine = make_async_engine(DATABASE_URL)
AsyncSessionLocal = make_session_factory(async_engine)

# Base class: Mọi bảng dữ liệu (Models) sau này sẽ kế thừa từ class này
Base = declarative_base()


# Hàm hỗ trợ lấy kết nối DB cho các API
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    """
    1 AsyncSession / request. `async with` luôn đóng session (rollback transaction
    còn dở, trả kết nối về pool) kể cả khi endpoint ném lỗi.
    """
    async with AsyncSessionLocal() as session:
        yield session


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
        # Thứ tự thiết bị trên Dashboard, đồng bộ theo tài khoản. Nullable,
        # không default: hàng cũ = NULL = thứ tự mặc định.
        "sort_order": {"sqlite": "JSON", "postgresql": "JSONB"},
    },
    "scenes": {
        # Điều kiện chạy kịch bản. Nullable, không default: hàng cũ = NULL =
        # không điều kiện, chạy y như trước; `actions` không bị đụng tới.
        "conditions": {"sqlite": "TEXT", "postgresql": "TEXT"},
    },
    "zones": {
        # Đợt 2 — khu dùng chung cả nhà.
        "is_shared": {
            "sqlite": "INTEGER NOT NULL DEFAULT 0",
            "postgresql": "BOOLEAN NOT NULL DEFAULT FALSE",
        },
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
    "members": {"user_id", "email", "display_name", "role", "status", "avatar_color", "sort_order"},
    "zones": {"id", "name", "sort_order", "is_shared"},
    "member_zone_access": {"user_id", "zone_id"},
    "scenes": {"id", "name", "icon", "sort_order", "actions", "created_by", "conditions"},
    "command_logs": {
        "id", "at_ms", "device_id", "device_name", "action_type", "action_value",
        "action_label", "source", "user_id", "user_name", "success", "detail", "ext_id",
    },
    # Bảng mới (create_all tạo) — có trong đây để enable_rls bật RLS cho nó.
    "floor_plans": {"id", "layout", "updated_by", "updated_at_ms"},
    # Chống bắn trùng + phục hồi của bộ hẹn giờ (services/scheduler.py, worker/).
    "schedule_runs": {
        "id", "schedule_id", "part", "occurrence", "due_at_ms", "label", "device_id",
        "brand", "action_type", "action_value", "status", "attempts", "worker_id",
        "claimed_at_ms", "updated_at_ms", "detail",
    },
    "scheduler_heartbeats": {
        "worker_id", "role", "host", "pid", "state", "started_at_ms", "last_seen_ms", "detail",
    },
}


@contextmanager
def _begin(bind):
    """
    Transaction để ghi DDL/seed trên `bind`:
      - Engine (test, worker cũ): mở kết nối + transaction riêng như trước.
      - Connection (lúc boot: `AsyncConnection.run_sync`): dùng chính kết nối đó,
        commit khi khối chạy xong; lỗi giữa chừng thì không commit — người gọi
        đóng kết nối là rollback.
    """
    if isinstance(bind, Engine):
        with bind.begin() as conn:
            yield conn
        return
    yield bind
    bind.commit()


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
        with _begin(bind) as conn:
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
    with _begin(bind) as conn:
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
    with _begin(bind) as conn:
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


def verify_schema(bind=None, tables=None) -> None:
    """
    Kiểm schema khớp với những gì code đọc/ghi. Raise nếu thiếu — lifespan bắt
    exception này và cho app boot ở chế độ degraded, /health báo db:false.
    Không có bước này thì schema lệch chỉ lộ ra lúc request đầu tiên lỗi 500.

    `tables`: chỉ kiểm các bảng này (worker hẹn giờ chỉ dùng vài bảng và có
    thể chạy bằng role DB quyền hẹp). None = tất cả.
    """
    bind = bind if bind is not None else engine
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    wanted = _REQUIRED_SCHEMA if tables is None else {t: _REQUIRED_SCHEMA[t] for t in tables}

    problems = []
    for table, required in wanted.items():
        if table not in existing_tables:
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
    _import_models()
    with _begin(bind) as conn:
        Base.metadata.create_all(bind=conn)
    run_startup_migrations(bind)
    # verify TRƯỚC seed: nếu schema lệch thì seed sẽ ném OperationalError thô
    # (stack trace SQLAlchemy), che mất thông báo nói rõ bảng/cột nào thiếu.
    verify_schema(bind)
    enable_rls(bind)
    seed_defaults(bind)


def _import_models() -> None:
    # import để models đăng ký vào Base.metadata trước khi create_all
    from app.models import (  # noqa: F401
        command_log, device, floor_plan, member, scene, schedule, schedule_run, zone,
    )


async def init_db_async(bind=None) -> None:
    """
    init_db trên engine ASYNC (lifespan của main.py). Cùng các bước đồng bộ ở
    trên, chạy qua `run_sync` trên MỘT kết nối của engine async: không cần
    driver đồng bộ (psycopg2) hay engine thứ hai chỉ để boot.
    """
    bind = bind if bind is not None else async_engine
    async with bind.connect() as conn:
        await conn.run_sync(init_db)
