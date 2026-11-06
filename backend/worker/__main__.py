"""
Điểm vào: `python -m worker [run|once|status] [--env-file PATH]` (chạy từ backend/).

Biến môi trường được nạp TRƯỚC khi import bất kỳ module `app.*` nào: database.py
đọc DATABASE_URL lúc import, connector đọc credential lúc khởi tạo.
Thứ tự tìm file .env: --env-file > WORKER_ENV_FILE > backend/worker/.env >
backend/.env. Biến môi trường thật (systemd EnvironmentFile...) luôn thắng file.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_env(explicit: str | None) -> str | None:
    from dotenv import load_dotenv

    candidates = [explicit, os.getenv("WORKER_ENV_FILE"),
                  BACKEND_DIR / "worker" / ".env", BACKEND_DIR / ".env"]
    for c in candidates:
        if c and Path(c).is_file():
            load_dotenv(c, override=False)
            return str(c)
    if explicit:
        raise SystemExit(f"Không tìm thấy file env: {explicit}")
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m worker",
                                     description="Worker Hẹn giờ SmartHome (chạy độc lập, không cần FastAPI).")
    parser.add_argument("command", nargs="?", default="run", choices=("run", "once", "status"),
                        help="run = chạy liên tục (mặc định) | once = 1 tick | status = sức khỏe")
    parser.add_argument("--env-file", help="đường dẫn file .env (mặc định worker/.env rồi backend/.env)")
    args = parser.parse_args(argv)
    # Trước MỌI dòng in ra: console Windows mặc định không phải UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    env_file = _load_env(args.env_file)
    if str(BACKEND_DIR) not in sys.path:  # để `import app` chạy được từ thư mục khác
        sys.path.insert(0, str(BACKEND_DIR))

    from worker.config import ConfigError, load_config

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"❌ Cấu hình worker sai: {e}", file=sys.stderr)
        return 2

    if args.command == "status":
        from worker.status import print_status
        return print_status(cfg)

    from worker.runner import run_worker, setup_logging
    setup_logging(cfg)
    if env_file:
        import logging
        logging.getLogger("SmartHome.Worker").info(f"Đã nạp biến môi trường từ {env_file}")
    try:
        return asyncio.run(run_worker(cfg, once=args.command == "once"))
    except KeyboardInterrupt:  # Ctrl+C lần 2
        return 130


if __name__ == "__main__":
    sys.exit(main())
