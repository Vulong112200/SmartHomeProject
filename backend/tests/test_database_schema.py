"""
Test cho app/core/database.py (Phase 1a — chuyển sang Postgres).

Chạy: cd backend && python -m pytest tests/test_database_schema.py -v
(phải là `python -m pytest`, không phải `pytest` trần — tests/ không có
__init__.py nên bare pytest sẽ ModuleNotFoundError: No module named 'app')

Đường Postgres chỉ test được phần không cần server (chuẩn hóa URL, chọn
dialect, dựng pool, chọn DDL). Phần chạy thật trên Postgres được verify khi
đặt DATABASE_URL — xem docs/SUPABASE_SETUP.md bước 5.
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

import app.core.database as db


@pytest.fixture
def temp_engine(tmp_path):
    """Engine SQLite trên file tạm. Dùng thay cho việc reload module.

    Không reload được: reload tạo lại `Base`, mà app.models đã nằm trong
    sys.modules nên không import lại => metadata rỗng => create_all không tạo gì.
    """
    return create_engine(f"sqlite:///{tmp_path / 'test.db'}")


def _engine_over(path):
    return create_engine(f"sqlite:///{path}")


# ---------------------------------------------------------------------
# Chọn DB theo môi trường
# ---------------------------------------------------------------------
def test_khong_co_env_thi_fallback_sqlite():
    assert db.normalize_database_url("") == "sqlite:///./smarthome.db"
    assert db.normalize_database_url("   ") == "sqlite:///./smarthome.db"


def test_postgres_url_duoc_chuan_hoa():
    """Supabase in ra "postgres://" nhưng SQLAlchemy 2.x chỉ nhận "postgresql://"."""
    url = db.normalize_database_url("postgres://u:p@host:5432/postgres")
    assert url == "postgresql://u:p@host:5432/postgres"
    # dạng đã đúng thì giữ nguyên
    assert db.normalize_database_url(url) == url


def test_postgres_dung_pool_co_pre_ping():
    """Render free ngủ thường xuyên -> kết nối chết; thiếu pre_ping là lỗi ngẫu nhiên."""
    engine = db.make_engine("postgresql://u:p@host:5432/postgres")
    assert engine.dialect.name == "postgresql"
    assert engine.pool.size() == 5
    assert engine.pool._pre_ping is True


def test_sqlite_cho_phep_dung_chung_nhieu_thread():
    """FastAPI chạy handler ở threadpool — thiếu cờ này là lỗi 'same thread'."""
    engine = db.make_engine("sqlite:///./x.db")
    assert engine.dialect.name == "sqlite"


# ---------------------------------------------------------------------
# init_db trên DB rỗng
# ---------------------------------------------------------------------
def test_db_rong_duoc_tao_bang_va_seed_3_thiet_bi(temp_engine):
    db.init_db(temp_engine)

    assert set(inspect(temp_engine).get_table_names()) >= {"devices", "schedules"}
    with temp_engine.begin() as conn:
        rows = conn.execute(text("SELECT id FROM devices")).fetchall()
    # id phải giữ nguyên: shortcut đã pin và slot Home Widget lưu theo brand+id
    assert {r[0] for r in rows} == {
        "a32aae46a67dbe52860pza",
        "vsaq325492d4dce9e0f8eb348bb3be41",
        "a32e6ab42d076b8bb5bbrh",
    }


def test_init_db_idempotent_khong_nhan_ban_seed(temp_engine):
    db.init_db(temp_engine)
    db.init_db(temp_engine)
    with temp_engine.begin() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM devices")).scalar() == 3


def test_seed_khong_ghi_de_du_lieu_nguoi_dung(temp_engine):
    """Người dùng đổi tên/xóa bớt thiết bị thì boot sau không được ghi đè lại."""
    db.init_db(temp_engine)
    with temp_engine.begin() as conn:
        conn.execute(text("DELETE FROM devices WHERE brand = 'rojeco'"))
        conn.execute(text("UPDATE devices SET name = 'Rèm phòng khách' WHERE brand = 'tuya'"))

    db.init_db(temp_engine)  # boot lại

    with temp_engine.begin() as conn:
        rows = dict(conn.execute(text("SELECT brand, name FROM devices")).fetchall())
    assert "rojeco" not in rows                # đã xóa thì không được seed lại
    assert rows["tuya"] == "Rèm phòng khách"   # tên đã sửa phải giữ nguyên


def test_lich_hen_song_sot_qua_lan_boot_sau(temp_engine):
    """Đây chính là lỗi Phase 1a sửa: dữ liệu phải còn sau khi khởi động lại."""
    db.init_db(temp_engine)
    with temp_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO schedules (brand, device_id, action_type, action_value, time, days, enabled) "
            "VALUES ('vesync', 'dev1', 'mode', '3', '17:45', '', 1)"
        ))

    db.init_db(temp_engine)

    with temp_engine.begin() as conn:
        assert conn.execute(text("SELECT time FROM schedules")).scalar() == "17:45"


# ---------------------------------------------------------------------
# Migration cột thiếu
# ---------------------------------------------------------------------
def test_bang_schedules_cu_duoc_them_cot_lich_khoang(tmp_path):
    """create_all KHÔNG ALTER bảng đã tồn tại — đây đúng là lỗ hổng migration lấp."""
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT, brand TEXT, is_active BOOLEAN)"
    )
    raw.execute(
        "CREATE TABLE schedules (id INTEGER PRIMARY KEY, name TEXT, brand TEXT, "
        "device_id TEXT, action_type TEXT, action_value TEXT, time TEXT, days TEXT, "
        "enabled BOOLEAN, last_fired_date TEXT)"
    )
    raw.execute(
        "INSERT INTO schedules (id, brand, device_id, action_type, time) "
        "VALUES (1, 'vesync', 'dev1', 'mode', '17:45')"
    )
    raw.commit()
    raw.close()

    engine = _engine_over(path)
    db.init_db(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("schedules")}
    assert {"end_time", "end_action_type", "end_action_value",
            "last_end_fired_date", "one_shot"} <= cols
    with engine.begin() as conn:  # lịch cũ không được mất
        assert conn.execute(text("SELECT time FROM schedules WHERE id = 1")).scalar() == "17:45"


def test_bang_members_cu_duoc_them_sort_order_khong_mat_ho_so(tmp_path):
    """members có từ trước (chưa có avatar_color/sort_order) -> thêm cột, hồ sơ/vai giữ nguyên."""
    path = tmp_path / "old_members.db"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE members (user_id TEXT PRIMARY KEY, email TEXT NOT NULL DEFAULT '', "
        "display_name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'guest', "
        "status TEXT NOT NULL DEFAULT 'pending')"
    )
    raw.execute(
        "INSERT INTO members VALUES ('u1', 'me@x.test', 'Bố', 'owner', 'active')"
    )
    raw.commit()
    raw.close()

    engine = _engine_over(path)
    db.init_db(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("members")}
    assert {"avatar_color", "sort_order"} <= cols
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT email, display_name, role, status, sort_order FROM members WHERE user_id = 'u1'"
        )).one()
    assert tuple(row) == ("me@x.test", "Bố", "owner", "active", None)


def test_bang_scenes_cu_duoc_them_cot_conditions_khong_mat_actions(tmp_path):
    """scenes có từ trước (chưa có conditions) -> thêm cột NULL, actions giữ nguyên."""
    path = tmp_path / "old_scenes.db"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE scenes (id INTEGER PRIMARY KEY, name TEXT NOT NULL, icon TEXT, "
        "sort_order INTEGER NOT NULL DEFAULT 0, actions TEXT NOT NULL DEFAULT '[]', created_by TEXT)"
    )
    actions = '[{"device_id": "d1", "action_type": "off", "action_value": null}]'
    raw.execute("INSERT INTO scenes (id, name, actions) VALUES (1, 'Ra khỏi nhà', ?)", (actions,))
    raw.commit()
    raw.close()

    engine = _engine_over(path)
    db.init_db(engine)
    db.init_db(engine)  # boot lần 2: idempotent, không ALTER lại

    assert "conditions" in {c["name"] for c in inspect(engine).get_columns("scenes")}
    with engine.begin() as conn:
        row = conn.execute(text("SELECT name, actions, conditions FROM scenes WHERE id = 1")).one()
    assert tuple(row) == ("Ra khỏi nhà", actions, None)


def test_ddl_sort_order_theo_dialect():
    ddl = db._WANTED_COLUMNS["members"]["sort_order"]
    assert ddl == {"sqlite": "JSON", "postgresql": "JSONB"}


def test_ddl_one_shot_khac_nhau_theo_dialect():
    """Boolean của SQLite là INTEGER, của Postgres là BOOLEAN — chung DDL sẽ lỗi."""
    ddl = db._WANTED_COLUMNS["schedules"]["one_shot"]
    assert ddl["sqlite"] == "INTEGER DEFAULT 0"
    assert ddl["postgresql"] == "BOOLEAN DEFAULT FALSE"


# ---------------------------------------------------------------------
# verify_schema
# ---------------------------------------------------------------------
def test_verify_schema_bao_ro_bang_thieu(temp_engine):
    with pytest.raises(RuntimeError) as err:
        db.verify_schema(temp_engine)
    assert "devices" in str(err.value)
    assert "schedules" in str(err.value)


def test_verify_schema_bao_ro_cot_thieu(tmp_path):
    """Thông báo phải nêu tên cột — nếu không, lỗi chỉ lộ ra ở request 500 đầu tiên."""
    path = tmp_path / "partial.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT)")
    raw.commit()
    raw.close()

    with pytest.raises(RuntimeError) as err:
        db.verify_schema(_engine_over(path))
    assert "brand" in str(err.value)


def test_verify_chay_truoc_seed(tmp_path):
    """
    Thứ tự quan trọng: seed trước verify thì schema lệch ném OperationalError
    thô của SQLAlchemy, che mất thông báo nói rõ thiếu cột nào.
    """
    path = tmp_path / "broken.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT)")
    raw.commit()
    raw.close()

    with pytest.raises(RuntimeError, match="Schema DB không khớp"):
        db.init_db(_engine_over(path))


# ---------------------------------------------------------------------
# RLS
# ---------------------------------------------------------------------
def test_enable_rls_bo_qua_sqlite(temp_engine):
    """SQLite không có RLS — gọi phải là no-op, không được ném lỗi."""
    db.init_db(temp_engine)
    db.enable_rls(temp_engine)  # không raise là đạt


# ---------------------------------------------------------------------
# Engine ASYNC (asyncpg / aiosqlite)
# ---------------------------------------------------------------------
def test_url_async_doi_driver():
    assert db.async_database_url("sqlite:///./smarthome.db").drivername == "sqlite+aiosqlite"
    u = db.async_database_url("postgresql://u:p@host:5432/postgres")
    assert u.drivername == "postgresql+asyncpg"
    # driver đồng bộ ghi sẵn cũng bị thay — cả backend chỉ một kiểu driver
    assert db.async_database_url("postgresql+psycopg2://u:p@h/d").drivername == "postgresql+asyncpg"


def test_url_async_giu_mat_khau_ky_tu_dac_biet():
    u = db.async_database_url("postgresql://u:p%40ss%2Fw@host:5432/postgres")
    assert u.password == "p@ss/w"


def test_sslmode_doi_sang_tham_so_asyncpg():
    """asyncpg.connect() không nhận `sslmode` — để nguyên trong URL là TypeError lúc kết nối."""
    raw = "postgresql://u:p@host:5432/postgres?sslmode=require&connect_timeout=5&application_name=x"
    u = db.async_database_url(raw)
    assert "sslmode" not in u.query and "connect_timeout" not in u.query
    args = db.async_connect_args(raw)
    assert args["ssl"] == "require"
    assert args["timeout"] == 5.0
    assert args["server_settings"]["application_name"] == "x"
    assert args["command_timeout"] == 30


def test_session_pooler_giu_prepared_statement():
    args = db.async_connect_args("postgresql://u:p@aws-0.pooler.supabase.com:5432/postgres")
    assert "statement_cache_size" not in args


def test_transaction_pooler_tat_prepared_statement():
    args = db.async_connect_args("postgresql://u:p@aws-0.pooler.supabase.com:6543/postgres")
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0
    a, b = args["prepared_statement_name_func"](), args["prepared_statement_name_func"]()
    assert a != b


def test_engine_async_postgres_co_pool_va_pre_ping():
    engine = db.make_async_engine("postgresql://u:p@host:5432/postgres")
    assert engine.dialect.driver == "asyncpg"
    assert engine.pool.size() == 5
    assert engine.pool._pre_ping is True
    assert engine.pool._timeout == 10


def test_init_db_async_tren_aiosqlite(tmp_path):
    """Boot thật đi đường này: init_db chạy qua run_sync trên kết nối async."""
    import asyncio

    path = tmp_path / "async.db"
    engine = db.make_async_engine(f"sqlite:///{path}")

    async def go():
        await db.init_db_async(engine)
        await db.init_db_async(engine)  # idempotent: boot lần 2 không seed/ALTER lại
        await engine.dispose()

    asyncio.run(go())
    check = _engine_over(path)
    with check.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM devices")).scalar() == 3
        assert conn.execute(text("SELECT COUNT(*) FROM zones")).scalar() == 1
    assert "schedule_runs" in inspect(check).get_table_names()


def test_init_db_async_verify_loi_thi_nem(tmp_path):
    """Schema lệch -> RuntimeError rõ ràng (lifespan bắt -> boot degraded)."""
    import asyncio

    path = tmp_path / "broken.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE scenes (id INTEGER PRIMARY KEY)")  # thiếu cột, không ALTER được hết
    raw.commit()
    raw.close()
    engine = db.make_async_engine(f"sqlite:///{path}")

    async def go():
        try:
            await db.init_db_async(engine)
        finally:
            await engine.dispose()

    with pytest.raises(RuntimeError, match="scenes"):
        asyncio.run(go())
