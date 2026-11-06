"""
`python -m worker status` — sức khỏe bộ hẹn giờ, chạy được từ BẤT KỲ máy nào có
DATABASE_URL (không cần worker đang chạy trên máy đó). Chỉ ĐỌC.

Mã thoát: 0 = có worker đang chạy (nhịp tim mới), 1 = không có, 2 = không đọc
được DB — dùng được trong script giám sát / cron.
"""
import asyncio
from datetime import datetime

from sqlalchemy import select, text

from app.core.household import scheduler_target_device
from app.models.schedule import ScheduleModel
from app.models.schedule_run import RUN_OPEN, ScheduleRunModel, SchedulerHeartbeatModel
from app.services.device_actions import normalize_action
from app.services.scheduler import HEARTBEAT_FRESH_SECONDS, TZ

from .config import WorkerConfig
from app.core.database import make_session_factory

from .db import check_db, describe, make_worker_engine

_DAY = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


def _ago(ms: int, now_ms: int) -> str:
    s = max(0, (now_ms - ms) // 1000)
    if s < 120:
        return f"{s}s trước"
    if s < 7200:
        return f"{s // 60} phút trước"
    return f"{s // 3600} giờ trước"


def _days(days: str) -> str:
    parts = [p for p in (days or "").split(",") if p.strip().isdigit()]
    return "mỗi ngày" if not parts else ",".join(_DAY[int(p)] for p in parts if int(p) < 7)


def _local(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%d/%m %H:%M:%S")


def print_status(cfg: WorkerConfig) -> int:
    return asyncio.run(_print_status(cfg))


async def _print_status(cfg: WorkerConfig) -> int:
    engine = make_worker_engine(cfg.database_url)
    print(f"Database : {describe(engine)}")
    try:
        await check_db(engine)
    except Exception as e:
        print(f"  ❌ {e}")
        await engine.dispose()
        return 2
    print("  ✅ kết nối + schema OK")

    db = make_session_factory(engine)()
    try:
        if not cfg.is_sqlite:
            db_now = (await db.execute(text("SELECT clock_timestamp()"))).scalar()
            skew = (datetime.now(TZ) - db_now).total_seconds()
            flag = "✅" if abs(skew) < 5 else "⚠️ "
            print(f"Đồng hồ  : {flag} máy này lệch {skew:+.1f}s so với DB "
                  "(worker dùng giờ DB nên lệch không làm sai giờ hẹn)")
            now_ms = int(db_now.timestamp() * 1000)
        else:
            now_ms = int(datetime.now(TZ).timestamp() * 1000)

        H = SchedulerHeartbeatModel
        beats = (await db.execute(select(H).where(H.last_seen_ms >= now_ms - 86_400_000)
                                  .order_by(H.last_seen_ms.desc()).limit(10))).scalars().all()
        print("\nTiến trình hẹn giờ (24h qua):")
        if not beats:
            print("  (chưa có nhịp tim nào)")
        worker_alive = False
        for b in beats:
            fresh = now_ms - b.last_seen_ms <= HEARTBEAT_FRESH_SECONDS * 1000
            alive = fresh and b.state in ("running", "standby")
            worker_alive = worker_alive or (alive and b.role == "worker" and b.state == "running")
            mark = "🟢" if alive else "⚪"
            print(f"  {mark} {b.role:<6} {b.state:<8} {_ago(b.last_seen_ms, now_ms):<14} "
                  f"{b.worker_id}  {b.detail or ''}")

        R = ScheduleRunModel
        open_runs = (await db.execute(
            select(R).where(R.status.in_(RUN_OPEN)).order_by(R.due_at_ms))).scalars().all()
        if open_runs:
            print("\nLần chạy CHƯA xong (claimed/sending/retry):")
            for r in open_runs:
                print(f"  #{r.id} lịch #{r.schedule_id} {r.occurrence} {r.part} {r.status} "
                      f"lần {r.attempts} — {r.worker_id}")

        print("\n15 lần chạy gần nhất:")
        recent = (await db.execute(select(R).order_by(R.claimed_at_ms.desc()).limit(15))).scalars().all()
        if not recent:
            print("  (chưa có)")
        for r in recent:
            icon = {"success": "✅", "retry": "🔁", "claimed": "⏳", "sending": "⏳"}.get(r.status, "❌")
            print(f"  {icon} {_local(r.claimed_at_ms)}  {r.label or r.device_id} ({r.part} "
                  f"{r.action_type} {r.action_value or ''}) → {r.status}"
                  f"{f' ×{r.attempts}' if (r.attempts or 0) > 1 else ''}  {r.detail or ''}")

        print("\nLịch đang bật:")
        problems = 0
        schedules = (await db.execute(
            select(ScheduleModel).where(ScheduleModel.enabled == True).order_by(ScheduleModel.time)  # noqa: E712
        )).scalars().all()
        for s in schedules:
            device = await scheduler_target_device(db, s.device_id)
            notes = []
            if device is None:
                notes.append("❌ thiết bị không còn")
            else:
                for at, av, tag in ((s.action_type, s.action_value, "start"),
                                    (s.end_action_type, s.end_action_value, "end")):
                    if tag == "end" and not s.end_time:
                        continue
                    try:
                        normalize_action(device, at, av)
                    except ValueError as e:
                        notes.append(f"❌ {tag}: {e} — sẽ KHÔNG gửi")
            problems += bool(notes)
            span = f"{s.time}→{s.end_time}" if s.end_time else s.time
            print(f"  #{s.id:<4} {span:<12} {_days(s.days):<14} {s.name or s.device_id}"
                  f"{' (1 lần)' if s.one_shot else ''}  {' '.join(notes)}")
        if problems:
            print(f"\n⚠️  {problems} lịch sẽ bị từ chối khi đến giờ — sửa trong tab Hẹn giờ.")

        print(f"\n{'✅ Có worker đang chạy.' if worker_alive else '⚠️  KHÔNG có worker nào đang chạy.'}")
        return 0 if worker_alive else 1
    finally:
        await db.close()
        await engine.dispose()
