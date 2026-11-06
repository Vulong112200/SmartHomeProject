"""Vòng đời worker: log → chờ DB → connector → vòng lặp hẹn giờ → dừng sạch."""
import asyncio
import logging
import signal
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.services.connector_manager import device_manager, register_default_connectors
from app.services.scheduler import ScheduleEngine, make_worker_id, run_forever

from .config import WorkerConfig
from .db import describe, make_worker_engine, wait_for_db

logger = logging.getLogger("SmartHome.Worker")

BACKEND_DIR = Path(__file__).resolve().parent.parent


def setup_logging(cfg: WorkerConfig) -> None:
    """stdout (systemd/journald, Task Scheduler) + file xoay vòng nếu đặt WORKER_LOG_FILE."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    handlers = [logging.StreamHandler(sys.stdout)]
    if cfg.log_file:
        path = Path(cfg.log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"))
    root = logging.getLogger()
    root.handlers.clear()
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)
    root.setLevel(getattr(logging, cfg.log_level, logging.INFO))


def code_version() -> str:
    """Commit đang chạy — để biết máy ở nhà đã cập nhật chưa (`status`)."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BACKEND_DIR,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "?"
    except Exception:
        return "?"


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """SIGTERM (systemd stop) / Ctrl+C → dừng SAU tick hiện tại. Bấm Ctrl+C lần 2 = thoát ngay."""
    loop = asyncio.get_running_loop()

    def request_stop(*_):
        if not stop.is_set():
            logger.info("🛑 Nhận lệnh dừng — chờ tick hiện tại xong (không cắt ngang lệnh đang gửi)...")
            loop.call_soon_threadsafe(stop.set)
            signal.signal(signal.SIGINT, signal.default_int_handler)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows: event loop không hỗ trợ add_signal_handler.
            try:
                signal.signal(sig, request_stop)
            except (ValueError, OSError):
                pass


async def run_worker(cfg: WorkerConfig, once: bool = False) -> int:
    version = code_version()
    engine = make_worker_engine(cfg.database_url)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    stop = asyncio.Event()
    _install_signal_handlers(stop)

    logger.info(f"🏠 Worker Hẹn giờ khởi động — code {version}, DB {describe(engine)}, "
                f"tick {cfg.tick_seconds}s{' (1 tick)' if once else ''}.")
    if cfg.is_sqlite:
        logger.warning("⚠️ Worker đang dùng SQLite (WORKER_ALLOW_SQLITE=1) — chỉ dùng để dev/test.")

    try:
        if not await wait_for_db(engine, stop):
            return 0
        await register_default_connectors(device_manager)

        sched = ScheduleEngine(
            Session, worker_id=make_worker_id("worker"), role="worker",
            use_db_clock=not cfg.is_sqlite, info=f"v={version}",
        )
        logger.info(f"⏰ Worker id {sched.worker_id} bắt đầu bắn lịch.")
        try:
            if once:
                stats = await sched.tick()
                logger.info(f"⏰ Xong 1 tick: {stats}")
            else:
                await run_forever(sched, stop, cfg.tick_seconds)
        finally:
            await asyncio.to_thread(sched.mark_stopped)
        logger.info("👋 Worker đã dừng sạch.")
        return 0
    finally:
        engine.dispose()
