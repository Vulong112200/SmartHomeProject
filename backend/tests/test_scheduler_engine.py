"""
Bộ máy hẹn giờ dùng chung (FastAPI + worker tại nhà): đúng giờ, đúng một lần,
chống trùng giữa nhiều tiến trình, phục hồi sau crash, thử lại theo loại thiết bị.

KHÔNG gửi lệnh thật: `scheduler.execute_schedule_action` bị thay bằng bản ghi giả.
"""
import asyncio
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace as D

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.database import init_db
from app.models.command_log import CommandLogModel
from app.models.device import DeviceModel
from app.models.schedule import ScheduleModel
from app.models.schedule_run import (
    RUN_ABANDONED, RUN_CLAIMED, RUN_FAILED, RUN_REJECTED, RUN_RETRY, RUN_SENDING, RUN_SUCCESS,
    ScheduleRunModel, SchedulerHeartbeatModel,
)
from app.services import scheduler
from app.services.scheduler import TZ, ScheduleEngine, _Snap, _to_ms
from conftest import async_factory_for


def at(day, h, m, s=0):
    """2026-07-20 là Thứ 2 (weekday 0). day = số ngày cộng thêm."""
    return datetime(2026, 7, 20, h, m, s, tzinfo=TZ) + timedelta(days=day)


@pytest.fixture
def env(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'sched.db'}"
    engine = create_engine(url, connect_args={"timeout": 30})
    init_db(engine)
    Session = sessionmaker(bind=engine)
    # Bộ máy chạy AsyncSession (như production); test chuẩn bị/kiểm bằng Session đồng bộ.
    ASession = async_factory_for(tmp_path / 'sched.db')
    with Session() as s:
        s.add_all([
            DeviceModel(id="pur", name="Lọc không khí", brand="vesync", category="purifier"),
            DeviceModel(id="door", name="Cửa cuốn", brand="tuya", category="curtain"),
            DeviceModel(id="feed", name="Máy cho mèo ăn", brand="rojeco", category="feeder"),
            DeviceModel(id="pump", name="Máy bơm", brand="tuya", category="switch"),
        ])
        s.commit()

    sent = []
    behavior = {}  # device_id -> "ok" | "fail" | "raise"

    async def fake_exec(brand, device_id, action_type, action_value, invalidate_cache=None):
        sent.append((brand, device_id, action_type, action_value))
        await asyncio.sleep(0)  # nhường event loop: tiến trình khác chen vào giữa lúc gửi
        mode = behavior.get(device_id, "ok")
        if mode == "raise":
            raise RuntimeError("mất mạng giữa chừng")
        return mode == "ok"

    monkeypatch.setattr(scheduler, "execute_schedule_action", fake_exec)

    def add(**kw):
        base = dict(name="Lịch", brand="vesync", device_id="pur", action_type="on",
                    action_value=None, time="16:30", days="", enabled=True)
        base.update(kw)
        with Session() as s:
            row = ScheduleModel(**base)
            s.add(row)
            s.commit()
            return row.id

    def make(role="worker", wid=None, **kw):
        return ScheduleEngine(ASession, worker_id=wid or f"{role}-test", role=role, **kw)

    def aclaim(eng, snap, part, now):
        async def go():
            async with ASession() as s:
                return await eng.claim(s, snap, part, now)
        return asyncio.run(go())

    def sch(sid):
        with Session() as s:
            return s.get(ScheduleModel, sid)

    def runs(sid=None):
        with Session() as s:
            q = s.query(ScheduleRunModel)
            if sid is not None:
                q = q.filter(ScheduleRunModel.schedule_id == sid)
            return q.order_by(ScheduleRunModel.id).all()

    def history():
        with Session() as s:
            return s.query(CommandLogModel).order_by(CommandLogModel.id).all()

    def tick(eng, now):
        return asyncio.run(eng.tick(now))

    yield D(url=url, path=tmp_path / 'sched.db', engine=engine, Session=Session, ASession=ASession,
            sent=sent, behavior=behavior, add=add, aclaim=aclaim,
            make=make, sch=sch, runs=runs, history=history, tick=tick)
    engine.dispose()


# =========================================================
# Đúng giờ, đúng một lần
# =========================================================
def test_lich_don_chay_dung_mot_lan_trong_cua_so(env):
    sid = env.add()
    eng = env.make()
    for t in (at(0, 16, 29, 50), at(0, 16, 30, 5), at(0, 16, 30, 35), at(0, 16, 31, 5), at(0, 16, 31, 50)):
        env.tick(eng, t)
    assert env.sent == [("vesync", "pur", "on", None)]
    assert env.sch(sid).last_fired_date == "2026-07-20"
    (run,) = env.runs(sid)
    assert (run.status, run.attempts, run.occurrence) == (RUN_SUCCESS, 1, "2026-07-20T16:30")
    (log,) = env.history()
    assert (log.source, log.success, log.user_id) == ("schedule", True, None)


def test_restart_worker_khong_gui_lap(env):
    env.add()
    env.tick(env.make(wid="w#1"), at(0, 16, 30, 5))
    env.tick(env.make(wid="w#2"), at(0, 16, 30, 40))  # tiến trình mới, cùng cửa sổ
    assert len(env.sent) == 1


def test_lich_lap_theo_thu(env):
    env.add(days="0,2")  # Thứ 2, Thứ 4
    eng = env.make()
    for day in range(8):
        env.tick(eng, at(day, 16, 30, 10))
    # 20/7 T2, 22/7 T4, 27/7 T2
    assert len(env.sent) == 3
    assert [r.occurrence for r in env.runs()] == ["2026-07-20T16:30", "2026-07-22T16:30", "2026-07-27T16:30"]


def test_lich_mot_lan_tu_tat_sau_khi_chay(env):
    sid = env.add(one_shot=True)
    eng = env.make()
    env.tick(eng, at(0, 16, 30, 10))
    env.tick(eng, at(7, 16, 30, 10))
    assert len(env.sent) == 1 and env.sch(sid).enabled is False


def test_lich_mot_lan_lo_gio_tu_tat_khong_ban(env):
    sid = env.add(one_shot=True, days="0")
    env.tick(env.make(), at(0, 16, 45))  # máy ngủ qua cửa sổ
    assert env.sent == [] and env.sch(sid).enabled is False


def test_lich_khoang_ban_ca_start_va_end(env):
    env.add(action_type="mode", action_value="3", end_time="17:30",
            end_action_type="mode", end_action_value="2")
    eng = env.make()
    env.tick(eng, at(0, 16, 30, 5))
    env.tick(eng, at(0, 17, 0))
    env.tick(eng, at(0, 17, 30, 5))
    env.tick(eng, at(0, 17, 31))
    assert env.sent == [("vesync", "pur", "mode", "3"), ("vesync", "pur", "mode", "2")]
    assert [r.part for r in env.runs()] == ["start", "end"]


def test_lich_qua_dem_end_vao_hom_sau(env):
    sid = env.add(time="22:00", days="0", end_time="06:00", end_action_type="off", one_shot=True)
    eng = env.make()
    env.tick(eng, at(0, 6, 0, 10))   # sáng Thứ 2: CHƯA được bắn end
    env.tick(eng, at(0, 22, 0, 10))  # tối Thứ 2: start
    assert env.sch(sid).enabled is True  # one-shot khoảng: còn chờ end
    env.tick(eng, at(1, 6, 0, 10))   # sáng Thứ 3: end
    assert env.sent == [("vesync", "pur", "on", None), ("vesync", "pur", "off", None)]
    s = env.sch(sid)
    assert (s.last_fired_date, s.last_end_fired_date, s.enabled) == ("2026-07-20", "2026-07-21", False)


def test_bat_lai_lich_trong_cung_cua_so_khong_ban_lan_hai(env):
    """Reset last_fired_date (PATCH bật lại) trong cùng occurrence: UNIQUE chặn lần 2."""
    sid = env.add()
    eng = env.make()
    env.tick(eng, at(0, 16, 30, 5))
    with env.Session() as s:
        s.get(ScheduleModel, sid).last_fired_date = None
        s.commit()
    env.tick(eng, at(0, 16, 30, 40))
    assert len(env.sent) == 1


def test_doi_gio_trong_ngay_thi_ban_theo_gio_moi(env):
    sid = env.add()
    eng = env.make()
    env.tick(eng, at(0, 16, 30, 5))
    with env.Session() as s:  # đúng việc PATCH làm khi đổi giờ
        row = s.get(ScheduleModel, sid)
        row.time, row.last_fired_date = "16:45", None
        s.commit()
    env.tick(eng, at(0, 16, 45, 5))
    assert len(env.sent) == 2


# =========================================================
# Chống trùng giữa nhiều tiến trình
# =========================================================
def test_claim_compare_and_set_anh_chup_cu_bi_tu_choi(env):
    sid = env.add()
    with env.Session() as s:
        snap = _Snap.of(s.get(ScheduleModel, sid))
    a, b = env.make(wid="A"), env.make(wid="B")
    assert env.aclaim(a, snap, "start", at(0, 16, 30, 5)) is not None
    # B đọc trước khi A ghi (ảnh chụp cũ) — vẫn phải thua.
    assert env.aclaim(b, snap, "start", at(0, 16, 30, 6)) is None


def test_claim_tu_choi_khi_lich_vua_bi_sua(env):
    sid = env.add()
    with env.Session() as s:
        snap = _Snap.of(s.get(ScheduleModel, sid))
    with env.Session() as s:
        s.get(ScheduleModel, sid).action_type = "off"
        s.commit()
    assert env.aclaim(env.make(), snap, "start", at(0, 16, 30, 5)) is None
    assert env.runs() == []


def test_tam_tien_trinh_tranh_cung_mot_lich_chi_mot_thang(env):
    sid = env.add()
    with env.Session() as s:
        snap = _Snap.of(s.get(ScheduleModel, sid))
    barrier = threading.Barrier(8)
    wins, errors = [], []

    def contender(i):
        # Mỗi "tiến trình" = 1 thread với event loop + engine async riêng.
        factory = async_factory_for(env.path)

        async def go():
            async with factory() as s:
                barrier.wait()
                return await ScheduleEngine(factory, worker_id=f"T{i}", role="worker").claim(
                    s, snap, "start", at(0, 16, 30, 5))
        try:
            if asyncio.run(go()) is not None:
                wins.append(i)
        except Exception as e:  # pragma: no cover — báo rõ nếu có
            errors.append(e)

    threads = [threading.Thread(target=contender, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(wins) == 1
    assert len(env.runs()) == 1


def test_hai_worker_chay_dong_thoi_khong_gui_trung(env):
    for i in range(5):
        env.add(device_id="pur", name=f"L{i}")
    a, b = env.make(wid="A"), env.make(wid="B")

    async def both():
        await asyncio.gather(a.tick(at(0, 16, 30, 5)), b.tick(at(0, 16, 30, 5)))
    asyncio.run(both())
    assert len(env.sent) == 5
    assert len(env.runs()) == 5


def test_api_va_worker_cung_chay_khong_trung(env):
    env.add()
    api, worker = env.make(role="api", wid="api#1"), env.make(role="worker", wid="w#1")
    env.tick(worker, at(0, 16, 30, 3))
    env.tick(api, at(0, 16, 30, 4))
    assert len(env.sent) == 1


# =========================================================
# Phục hồi sau crash / mất kết nối
# =========================================================
def _claim_only(env, sid, wid="dead", now=None):
    """Tiến trình giành quyền rồi chết TRƯỚC khi gửi."""
    with env.Session() as s:
        snap = _Snap.of(s.get(ScheduleModel, sid))
    return env.aclaim(env.make(wid=wid), snap, "start", now or at(0, 16, 30, 5))


def _set_run(env, rid, **values):
    with env.Session() as s:
        run = s.get(ScheduleRunModel, rid)
        for k, v in values.items():
            setattr(run, k, v)
        s.commit()


def test_crash_sau_claim_truoc_khi_gui_duoc_phuc_hoi_ca_may_cho_an(env):
    sid = env.add(brand="rojeco", device_id="feed", action_type="mode", action_value="2")
    rid = _claim_only(env, sid)
    eng = env.make(wid="new")
    env.tick(eng, at(0, 16, 31, 0))   # chưa hết lease → không đụng
    assert env.sent == []
    env.tick(eng, at(0, 16, 32, 0))   # hết lease 90s, còn trong cửa sổ 10 phút
    env.tick(eng, at(0, 16, 33, 0))
    assert env.sent == [("rojeco", "feed", "mode", "2")]
    assert env.runs()[0].status == RUN_SUCCESS and env.runs()[0].id == rid


def test_crash_sau_claim_qua_cua_so_thi_bo_va_ghi_lich_su(env):
    sid = env.add(device_id="door", brand="tuya", action_type="mode", action_value="close")
    _claim_only(env, sid)
    env.tick(env.make(), at(0, 16, 40))  # cửa: cửa sổ 3 phút đã qua
    assert env.sent == []
    assert env.runs()[0].status == RUN_ABANDONED
    log = env.history()[-1]
    assert log.success is False and "trước khi gửi" in log.detail


def test_crash_dang_gui_may_cho_an_khong_bao_gio_gui_lai(env):
    sid = env.add(brand="rojeco", device_id="feed", action_type="mode", action_value="1")
    rid = _claim_only(env, sid)
    _set_run(env, rid, status=RUN_SENDING, attempts=1)  # chết giữa lúc gửi / mất mạng trước khi có kết quả
    eng = env.make()
    env.tick(eng, at(0, 16, 32, 30))
    env.tick(eng, at(0, 16, 35))
    assert env.sent == []
    assert env.runs()[0].status == RUN_ABANDONED
    log = env.history()[-1]
    assert log.success is False and "KHÔNG gửi lại" in log.detail


def test_crash_dang_gui_may_loc_gui_lai_mot_lan(env):
    sid = env.add()
    rid = _claim_only(env, sid)
    _set_run(env, rid, status=RUN_SENDING, attempts=1)
    eng = env.make()
    env.tick(eng, at(0, 16, 32, 30))
    env.tick(eng, at(0, 16, 33, 30))
    assert env.sent == [("vesync", "pur", "on", None)]
    run = env.runs()[0]
    assert (run.status, run.attempts) == (RUN_SUCCESS, 2)
    assert "thử lại lần 2" in env.history()[-1].detail


def test_lich_bi_xoa_sau_claim_thi_khong_gui_lai(env):
    sid = env.add()
    _claim_only(env, sid)
    with env.Session() as s:
        s.delete(s.get(ScheduleModel, sid))
        s.commit()
    env.tick(env.make(), at(0, 16, 32, 30))
    assert env.sent == [] and env.runs()[0].status == RUN_ABANDONED


def test_lease_chua_het_thi_khong_gianh(env):
    sid = env.add()
    rid = _claim_only(env, sid)
    _set_run(env, rid, status=RUN_SENDING, attempts=1)
    env.tick(env.make(), at(0, 16, 31, 0))  # 55s sau claim < LEASE 90s
    assert env.sent == [] and env.runs()[0].status == RUN_SENDING


# =========================================================
# Thử lại theo loại thiết bị
# =========================================================
def test_may_loc_loi_thi_thu_lai_sau_backoff(env):
    env.add()
    env.behavior["pur"] = "fail"
    eng = env.make()
    env.tick(eng, at(0, 16, 30, 5))
    assert env.runs()[0].status == RUN_RETRY
    env.behavior["pur"] = "ok"
    # updated_at_ms của lần lỗi theo đồng hồ tick (16:30:05) → backoff 30s
    env.tick(eng, at(0, 16, 30, 20))
    assert len(env.sent) == 1
    env.tick(eng, at(0, 16, 30, 40))
    assert len(env.sent) == 2 and env.runs()[0].status == RUN_SUCCESS
    assert [h.success for h in env.history()] == [False, True]


def test_may_loc_het_luot_thi_dung(env):
    env.add()
    env.behavior["pur"] = "raise"
    eng = env.make()
    for sec in range(0, 600, 30):
        env.tick(eng, at(0, 16, 30, 5) + timedelta(seconds=sec))
    assert len(env.sent) == 3  # max_attempts của máy lọc
    assert env.runs()[0].status == RUN_FAILED


def test_may_cho_an_loi_khong_gui_lai(env):
    env.add(brand="rojeco", device_id="feed", action_type="mode", action_value="1")
    env.behavior["feed"] = "fail"
    eng = env.make()
    for sec in range(0, 300, 30):
        env.tick(eng, at(0, 16, 30, 5) + timedelta(seconds=sec))
    assert len(env.sent) == 1 and env.runs()[0].status == RUN_FAILED


def test_cua_cuon_thu_lai_trong_cua_so_ngan(env):
    env.add(brand="tuya", device_id="door", action_type="mode", action_value="close")
    env.behavior["door"] = "fail"
    eng = env.make()
    for sec in range(0, 600, 30):
        env.tick(eng, at(0, 16, 30, 5) + timedelta(seconds=sec))
    assert len(env.sent) == 2  # tối đa 2 lần, trong 3 phút
    assert env.runs()[0].status == RUN_FAILED


# =========================================================
# Quyền + chuẩn hóa hành động
# =========================================================
def test_cua_cuon_khong_bao_gio_nhan_on_off_tu_lich(env):
    env.add(brand="tuya", device_id="door", action_type="on")
    env.tick(env.make(), at(0, 16, 30, 5))
    assert env.sent == []
    assert env.runs()[0].status == RUN_REJECTED
    log = env.history()[-1]
    assert log.success is False and "không gửi" in log.detail


def test_hang_lay_tu_db_khong_tin_lich(env):
    env.add(brand="tuya", device_id="pur")  # lịch ghi sai hãng
    env.tick(env.make(), at(0, 16, 30, 5))
    assert env.sent == [("vesync", "pur", "on", None)]


def test_thiet_bi_da_xoa_thi_tu_choi(env):
    env.add(device_id="ghost", brand="tuya")
    env.tick(env.make(), at(0, 16, 30, 5))
    assert env.sent == [] and env.runs()[0].status == RUN_REJECTED


def test_loi_mot_lich_khong_chan_lich_khac(env, monkeypatch):
    bad = env.add(name="hỏng")
    env.add(name="tốt", device_id="pump", brand="tuya")
    real = ScheduleEngine._execute

    async def boom(self, db, run_id, now):
        if (await db.get(ScheduleRunModel, run_id)).schedule_id == bad:
            raise ValueError("lỗi dữ liệu")
        return await real(self, db, run_id, now)

    monkeypatch.setattr(ScheduleEngine, "_execute", boom)
    env.tick(env.make(), at(0, 16, 30, 5))
    assert env.sent == [("tuya", "pump", "on", None)]


# =========================================================
# Mất mạng / DB
# =========================================================
def test_mat_db_tick_loi_roi_tu_phuc_hoi(env):
    env.add()
    state = {"down": True}

    def flaky_session():
        if state["down"]:
            raise OperationalError("SELECT 1", {}, Exception("could not connect to server"))
        return env.ASession()

    eng = ScheduleEngine(flaky_session, worker_id="w", role="worker")
    with pytest.raises(OperationalError):
        env.tick(eng, at(0, 16, 30, 5))
    state["down"] = False
    env.tick(eng, at(0, 16, 30, 40))  # mạng quay lại, vẫn trong cửa sổ
    assert len(env.sent) == 1


def test_run_forever_khong_chet_khi_tick_loi():
    calls = []
    stop = asyncio.Event()

    class FakeEngine:
        async def tick(self):
            calls.append(1)
            if len(calls) < 3:
                raise OperationalError("x", {}, Exception("network down"))
            stop.set()

    asyncio.run(scheduler.run_forever(FakeEngine(), stop, tick_seconds=0))
    assert len(calls) == 3


# =========================================================
# Render đứng chờ khi worker sống (SCHEDULER_ENABLED=auto)
# =========================================================
def test_auto_api_dung_cho_khi_worker_song_va_tiep_quan_khi_worker_dung(env):
    env.add(time="16:30")
    env.add(time="17:00", name="L2")
    worker = env.make(role="worker", wid="w#1")
    api = env.make(role="api", wid="api#1", standby_when_worker_alive=True)

    env.tick(worker, at(0, 16, 29, 50))            # worker ghi nhịp tim (chưa tới giờ)
    assert env.tick(api, at(0, 16, 30, 5))["standby"] is True
    assert env.sent == []
    env.tick(worker, at(0, 16, 30, 20))            # worker bắn
    assert len(env.sent) == 1

    asyncio.run(worker.mark_stopped())             # tắt sạch → API tiếp quản NGAY
    assert env.Session().get(SchedulerHeartbeatModel, "w#1").state == "stopped"
    stats = env.tick(api, at(0, 16, 31))
    assert stats["standby"] is False
    stats = env.tick(api, at(0, 17, 0, 5))
    assert stats["standby"] is False and len(env.sent) == 2


def test_auto_api_tiep_quan_khi_nhip_tim_worker_qua_han(env):
    env.add(time="17:00")
    worker = env.make(role="worker", wid="w#1")
    api = env.make(role="api", wid="api#1", standby_when_worker_alive=True)
    env.tick(worker, at(0, 16, 50))   # nhịp tim cuối, rồi Pi mất điện
    env.tick(api, at(0, 17, 0, 5))     # 10 phút sau > HEARTBEAT_FRESH_SECONDS
    assert len(env.sent) == 1


@pytest.mark.parametrize("raw,mode", [("", "on"), ("1", "on"), ("0", "off"), ("auto", "auto"),
                                      ("AUTO", "auto"), ("false", "off"), ("rác", "on")])
def test_scheduler_mode(monkeypatch, raw, mode):
    monkeypatch.setenv("SCHEDULER_ENABLED", raw)
    assert scheduler.scheduler_mode() == mode


# =========================================================
# Dọn dẹp
# =========================================================
def test_don_nhat_ky_cu_giu_hang_dang_mo(env):
    sid = env.add()
    old = _to_ms(at(-40, 9, 0))
    with env.Session() as s:
        for i, st in enumerate((RUN_SUCCESS, RUN_CLAIMED)):
            s.add(ScheduleRunModel(schedule_id=sid, part="start", occurrence=f"2026-06-0{i + 1}T09:00",
                                   due_at_ms=old, device_id="pur", action_type="on", status=st,
                                   attempts=1, claimed_at_ms=old, updated_at_ms=old))
        s.commit()
    env.tick(env.make(), at(0, 9, 0))
    # success cũ bị dọn; claimed cũ được phục hồi trước (→ abandoned, mới cập nhật) nên còn giữ
    assert [r.status for r in env.runs()] == [RUN_ABANDONED]
