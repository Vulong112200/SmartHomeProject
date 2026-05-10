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