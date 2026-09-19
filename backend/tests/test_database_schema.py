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
