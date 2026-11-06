"""
Kết nối database RIÊNG của worker (không dùng engine của backend).

Khác engine của backend: pool nhỏ (worker chỉ có 1 vòng lặp tuần tự), timeout
kết nối ngắn + TCP keepalive (mất Internet thì lỗi nhanh thay vì treo cả tick),
`pool_pre_ping` để tự nối lại sau khi mạng/Supabase quay lại.
"""
import asyncio
import logging

from sqlalchemy import create_engine, text

from app.core.database import verify_schema

logger = logging.getLogger("SmartHome.Worker.DB")

# Bảng worker đọc/ghi — chỉ kiểm những bảng này (worker có thể chạy bằng role
# quyền hẹp, không cần thấy members/zones...).
WORKER_TABLES = ("devices", "schedules", "schedule_runs", "scheduler_heartbeats", "command_logs")


def make_worker_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=600,
        pool_size=2,
        max_overflow=1,
        pool_timeout=15,
        connect_args={
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
            "application_name": "smarthome-scheduler-worker",
        },
    )


def describe(engine) -> str:
    """Chuỗi kết nối ĐÃ che mật khẩu — để log."""
    return engine.url.render_as_string(hide_password=True)


def check_db(engine) -> None:
    """Nối được + đủ bảng/cột. Raise với thông báo rõ nếu không."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    try:
        verify_schema(engine, tables=WORKER_TABLES)
    except RuntimeError as e:
        raise RuntimeError(
            f"{e} — Worker KHÔNG tự tạo bảng (chạy được bằng role quyền hẹp). Deploy bản "
            "backend mới lên Render (create_all tạo bảng lúc boot) hoặc chạy "
            "backend/docs/supabase_schema.sql trên Supabase."
        ) from e


async def wait_for_db(engine, stop: asyncio.Event) -> bool:
    """
    Chờ tới khi DB dùng được (Pi khởi động trước khi có mạng, Supabase bảo
    trì...). Không thoát: thoát thì systemd khởi động lại liên tục mà không
    thêm được gì. Trả False nếu được yêu cầu dừng trong lúc chờ.
    """
    delay, last_error = 5.0, None
    while not stop.is_set():
        try:
            await asyncio.to_thread(check_db, engine)
            if last_error:
                logger.info("✅ Database đã dùng được.")
            return True
        except Exception as e:
            msg = str(e).splitlines()[0][:300]
            if msg != last_error:
                logger.error(f"❌ Chưa dùng được database ({describe(engine)}): {msg} — thử lại sau {delay:.0f}s.")
                last_error = msg
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        delay = min(delay * 2, 60.0)
    return False
