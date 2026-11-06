"""
Worker hẹn giờ tại nhà (`python -m worker`): chạy độc lập không cần FastAPI,
cấu hình chỉ từ biến môi trường, `once`/`status` hoạt động trên DB thật (SQLite tạm).
KHÔNG gửi lệnh thật: connector không được khởi tạo, lệnh đi qua bản ghi giả.
"""
import asyncio
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import init_db
from app.models.device import DeviceModel
from app.models.schedule import ScheduleModel
from app.models.schedule_run import RUN_SUCCESS, ScheduleRunModel, SchedulerHeartbeatModel
from app.services import scheduler
from app.services.scheduler import TZ

BACKEND = Path(__file__).resolve().parent.parent

_WORKER_ENV = ("WORKER_DATABASE_URL", "DATABASE_URL", "WORKER_ALLOW_SQLITE", "WORKER_TICK_SECONDS",
               "WORKER_LOG_FILE", "WORKER_ENV_FILE")


@pytest.fixture(autouse=True)
def _clean_worker_env(monkeypatch):
    for name in _WORKER_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'worker.db'}"
    engine = create_engine(url)
    init_db(engine)
    with sessionmaker(bind=engine)() as s:
        s.add(DeviceModel(id="pur", name="Lọc không khí", brand="vesync", category="purifier"))
        s.commit()
    engine.dispose()
    return url


# =========================================================
# Cấu hình
# =========================================================
def test_thieu_database_url_thi_tu_choi_chay():
    from worker.config import ConfigError, load_config
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_config()


def test_sqlite_phai_bat_co_rieng(monkeypatch):
    from worker.config import ConfigError, load_config
    monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db")
    with pytest.raises(ConfigError, match="WORKER_ALLOW_SQLITE"):
        load_config()
    monkeypatch.setenv("WORKER_ALLOW_SQLITE", "1")
    assert load_config().is_sqlite


def test_worker_database_url_thang_database_url_va_sua_postgres_scheme(monkeypatch):
    from worker.config import load_config
    monkeypatch.setenv("DATABASE_URL", "postgresql://backend@h/db")
    monkeypatch.setenv("WORKER_DATABASE_URL", "postgres://worker@h/db")
    assert load_config().database_url == "postgresql://worker@h/db"


@pytest.mark.parametrize("tick", ["0", "120", "abc"])
def test_tick_ngoai_khoang_bi_tu_choi(monkeypatch, tick):
    from worker.config import ConfigError, load_config
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@h/db")
    monkeypatch.setenv("WORKER_TICK_SECONDS", tick)
    with pytest.raises(ConfigError):
        load_config()


# =========================================================
# Độc lập với FastAPI
# =========================================================
def test_worker_khong_nap_fastapi_app_hay_uvicorn():
    code = ("import sys, worker.runner, worker.status, worker.db; "
            "bad = [m for m in ('app.main', 'uvicorn') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    env = {k: v for k, v in os.environ.items() if k not in _WORKER_ENV}
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr


def test_cli_bao_loi_cau_hinh_ma_2(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in _WORKER_ENV}
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "worker", "status", "--env-file", str(empty_env)],
                       cwd=BACKEND, capture_output=True, text=True, env=env, encoding="utf-8")
    assert r.returncode == 2 and "DATABASE_URL" in r.stderr


# =========================================================
# Chạy thật 1 tick trên DB tạm
# =========================================================
def test_run_worker_once_ban_lich_den_han_va_ghi_nhip_tim(db_url, monkeypatch):
    from worker import runner
    from worker.config import WorkerConfig

    sent = []

    async def fake_exec(brand, device_id, action_type, action_value, invalidate_cache=None):
        sent.append((brand, device_id, action_type))
        return True

    async def no_connectors(*a, **k):
        return None

    monkeypatch.setattr(scheduler, "execute_schedule_action", fake_exec)
    monkeypatch.setattr(runner, "register_default_connectors", no_connectors)

    hhmm = datetime.now(TZ).strftime("%H:%M")  # đến hạn ngay (0–59s < grace 120s)
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        s.add(ScheduleModel(name="Ngay", brand="vesync", device_id="pur", action_type="on",
                            time=hhmm, days="", enabled=True))
        s.commit()

    cfg = WorkerConfig(database_url=db_url, tick_seconds=30, log_file=None, log_level="INFO")
    assert asyncio.run(runner.run_worker(cfg, once=True)) == 0
    assert sent == [("vesync", "pur", "on")]

    with Session() as s:
        (run,) = s.query(ScheduleRunModel).all()
        (hb,) = s.query(SchedulerHeartbeatModel).all()
        assert run.status == RUN_SUCCESS and run.worker_id.startswith("worker:")
        assert (hb.role, hb.state) == ("worker", "stopped")  # dừng sạch → Render tiếp quản ngay
    engine.dispose()

    # Chạy lại (restart) trong cùng phút: không gửi lần 2.
    assert asyncio.run(runner.run_worker(cfg, once=True)) == 0
    assert len(sent) == 1


def test_wait_for_db_tra_false_khi_duoc_yeu_cau_dung():
    from worker.db import make_worker_engine, wait_for_db

    engine = make_worker_engine("sqlite:///Z:/khong/ton/tai/x.db")

    async def go():
        stop = asyncio.Event()
        stop.set()
        return await wait_for_db(engine, stop)
    assert asyncio.run(go()) is False


def test_check_db_bao_ro_thieu_bang(tmp_path):
    from worker.db import check_db, make_worker_engine
    engine = make_worker_engine(f"sqlite:///{tmp_path / 'trong.db'}")
    with pytest.raises(RuntimeError, match="schedule_runs"):
        check_db(engine)


# =========================================================
# status
# =========================================================
def test_status_ma_thoat_theo_nhip_tim_worker(db_url, capsys):
    from worker.config import WorkerConfig
    from worker.status import print_status

    cfg = WorkerConfig(database_url=db_url, tick_seconds=30, log_file=None, log_level="INFO")
    assert print_status(cfg) == 1
    assert "KHÔNG có worker" in capsys.readouterr().out

    engine = create_engine(db_url)
    with sessionmaker(bind=engine)() as s:
        now_ms = int(datetime.now(TZ).timestamp() * 1000)
        s.add(SchedulerHeartbeatModel(worker_id="worker:pi#1", role="worker", host="pi", pid=1,
                                      state="running", started_at_ms=now_ms, last_seen_ms=now_ms))
        s.add(ScheduleModel(name="Cửa sai", brand="vesync", device_id="pur", action_type="mode",
                            action_value="open", time="07:00", days="", enabled=True))
        s.commit()
    engine.dispose()
    assert print_status(cfg) == 0
    out = capsys.readouterr().out
    assert "worker:pi#1" in out and "sẽ KHÔNG gửi" in out
