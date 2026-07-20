# backend/app/core/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Định nghĩa đường dẫn file Database (SQLite)
# File 'smarthome.db' sẽ tự động được tạo ra trong thư mục backend
SQLALCHEMY_DATABASE_URL = "sqlite:///./smarthome.db"

# Khởi tạo Engine kết nối
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
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


def run_startup_migrations(engine) -> None:
    """
    Migration nhẹ cho SQLite: create_all KHÔNG thêm cột vào bảng đã tồn tại,
    nên các cột mới phải ALTER TABLE thủ công ở đây. Idempotent — chỉ thêm cột thiếu.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "schedules" not in inspector.get_table_names():
        return  # bảng chưa tồn tại -> create_all sẽ tạo đủ cột, khỏi migrate

    existing = {col["name"] for col in inspector.get_columns("schedules")}
    wanted = {
        "end_time": "TEXT",
        "end_action_type": "TEXT",
        "end_action_value": "TEXT",
        "last_end_fired_date": "TEXT",
        "one_shot": "INTEGER DEFAULT 0",
    }
    missing = {name: ddl for name, ddl in wanted.items() if name not in existing}
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE schedules ADD COLUMN {name} {ddl}"))