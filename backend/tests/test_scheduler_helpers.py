# backend/tests/test_scheduler_helpers.py
from datetime import datetime

from app.services.scheduler import TZ, _is_time_due, _is_time_missed, _end_days


class FakeSch:
    def __init__(self, time, end_time, days=""):
        self.time, self.end_time, self.days = time, end_time, days


def _at(h, m, s=0):
    # 2026-07-20 là Thứ 2 (weekday 0)
    return datetime(2026, 7, 20, h, m, s, tzinfo=TZ)


def test_due_inside_grace_window():
    assert _is_time_due("16:30", "", _at(16, 30, 0))
    assert _is_time_due("16:30", "", _at(16, 31, 59))
    assert not _is_time_due("16:30", "", _at(16, 32, 0))   # hết grace 120s
    assert not _is_time_due("16:30", "", _at(16, 29, 59))  # chưa tới giờ


def test_due_respects_days():
    assert _is_time_due("16:30", "0", _at(16, 30))      # Thứ 2
    assert not _is_time_due("16:30", "1", _at(16, 30))  # Thứ 3


def test_missed_after_grace():
    assert _is_time_missed("16:30", "", _at(16, 32, 0))
    assert not _is_time_missed("16:30", "", _at(16, 31, 0))   # đang trong grace
    assert not _is_time_missed("16:30", "", _at(16, 0))        # chưa tới
    assert not _is_time_missed("16:30", "1", _at(16, 32))      # sai thứ


def test_end_days_same_day_range():
    sch = FakeSch("16:30", "17:30", days="0,2")
    assert _end_days(sch) == "0,2"  # end > start -> cùng ngày


def test_end_days_overnight_shifts_plus_one():
    sch = FakeSch("22:00", "06:00", days="0,6")
    assert _end_days(sch) == "1,0"  # Thứ 2 -> Thứ 3; CN -> Thứ 2


def test_end_days_overnight_daily_stays_empty():
    sch = FakeSch("22:00", "06:00", days="")
    assert _end_days(sch) == ""
