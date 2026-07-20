# backend/tests/test_vn_time_parser.py
# Chạy: cd backend && python -m pytest tests/ -q
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.vn_time_parser import extract_schedule_times, resolve_target_days

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


@pytest.mark.parametrize("text,start,end,day_offset,recurring", [
    ("hẹn 16 giờ 30 bật quạt lọc mức cao", "16:30", None, 0, False),
    ("16h30 bật quạt", "16:30", None, 0, False),
    ("16:30 bật quạt", "16:30", None, 0, False),
    ("6 giờ sáng mai mở cửa", "06:00", None, 1, False),
    ("4 giờ chiều tắt máy lọc", "16:00", None, 0, False),
    ("7 giờ rưỡi tối đóng cửa", "19:30", None, 0, False),
    ("8 giờ tối bật quạt", "20:00", None, 0, False),
    ("11 giờ đêm bật chế độ ngủ máy lọc", "23:00", None, 0, False),
    ("từ 16 giờ 30 đến 17 giờ 30 bật quạt mức cao", "16:30", "17:30", 0, False),
    ("từ 4 giờ đến 5 giờ chiều bật quạt", "16:00", "17:00", 0, False),
    ("từ 8 giờ tối đến 10 giờ bật quạt", "20:00", "22:00", 0, False),
    ("từ 22 giờ đến 6 giờ sáng bật chế độ ngủ", "22:00", "06:00", 0, False),  # qua đêm
    ("mỗi ngày 6 giờ sáng cho mèo ăn", "06:00", None, 0, True),
    ("hàng ngày 9 giờ tối đóng cửa", "21:00", None, 0, True),
    ("bảy giờ rưỡi tối bật quạt", "19:30", None, 0, False),
    ("16 giờ 30 phút bật quạt", "16:30", None, 0, False),
])
def test_extract_times(text, start, end, day_offset, recurring):
    r = extract_schedule_times(text)
    assert r is not None, f"không parse được: {text}"
    assert r["start"] == start
    assert r["end"] == end
    assert r["day_offset"] == day_offset
    assert r["recurring_daily"] == recurring


@pytest.mark.parametrize("text", [
    "bật quạt mức cao",
    "đóng cửa",
    "cho mèo ăn 2 phần",
    "mở cửa lên",
])
def test_no_time_returns_none(text):
    assert extract_schedule_times(text) is None


def test_cleaned_text_strips_time_and_period():
    r = extract_schedule_times("hẹn 7 giờ rưỡi tối đóng cửa")
    assert r is not None
    assert "giờ" not in r["cleaned_text"]
    assert "tối" not in r["cleaned_text"]
    assert "đóng cửa" in r["cleaned_text"]


def test_cleaned_head_tail_for_range():
    r = extract_schedule_times("16h30 bật quạt mức cao đến 17h30 chuyển mức trung bình")
    assert r is not None
    assert r["end"] == "17:30"
    assert "bật quạt mức cao" in (r["cleaned_head"] or "")
    assert "trung bình" in (r["cleaned_tail"] or "")


def test_resolve_target_days_future_today():
    now = datetime(2026, 7, 20, 10, 0, tzinfo=TZ)  # Thứ 2
    days, one_shot, rolled = resolve_target_days("16:30", 0, False, now)
    assert (days, one_shot, rolled) == ("0", True, False)


def test_resolve_target_days_rolls_to_tomorrow():
    now = datetime(2026, 7, 20, 22, 0, tzinfo=TZ)  # Thứ 2, 22h
    days, one_shot, rolled = resolve_target_days("06:00", 0, False, now)
    assert (days, one_shot, rolled) == ("1", True, True)


def test_resolve_target_days_tomorrow_offset():
    now = datetime(2026, 7, 20, 10, 0, tzinfo=TZ)
    days, one_shot, rolled = resolve_target_days("06:00", 1, False, now)
    assert (days, one_shot, rolled) == ("1", True, False)


def test_resolve_target_days_recurring():
    now = datetime(2026, 7, 20, 10, 0, tzinfo=TZ)
    assert resolve_target_days("06:00", 0, True, now) == ("", False, False)
