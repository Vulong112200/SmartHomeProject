# backend/app/services/vn_time_parser.py
"""
Parser biểu thức GIỜ tiếng Việt cho lệnh hẹn giờ (pure function, không I/O).

Nhận diện:
- Giờ số:   "16 giờ 30", "16 giờ 30 phút", "16h30", "16:30", "6g30", "7 giờ rưỡi"
- Giờ chữ:  "bảy giờ rưỡi", "mười giờ" (1-12; lớn hơn để AI fallback xử lý)
- Buổi:     sáng / trưa / chiều / tối / đêm (tìm quanh mốc giờ, vd "4 giờ chiều" -> 16:00)
- Ngày:     "mai / ngày mai / sáng mai" -> day_offset=1; "hôm nay" -> 0
- Lặp:      "mỗi ngày / hàng ngày / mỗi sáng / mỗi tối..." -> recurring_daily=True
- Khoảng:   "từ X đến/tới Y" -> start + end (end < start = khoảng QUA ĐÊM, hợp lệ)

Ví dụ bắt buộc pass (có test ở backend/tests/test_vn_time_parser.py):
    "hẹn 16 giờ 30 bật quạt lọc mức cao"        -> start 16:30
    "16h30 bật quạt" / "16:30 bật quạt"          -> start 16:30
    "6 giờ sáng mai mở cửa"                      -> start 06:00, day_offset 1
    "4 giờ chiều tắt máy lọc"                    -> start 16:00
    "7 giờ rưỡi tối đóng cửa"                    -> start 19:30
    "từ 16 giờ 30 đến 17 giờ 30 bật quạt mức cao"-> 16:30 -> 17:30
    "mỗi ngày 6 giờ sáng cho mèo ăn"             -> 06:00, recurring_daily
    "bật quạt mức cao" (không có giờ)            -> None
"""
import re
from datetime import datetime, timedelta
from typing import Optional

# --- Regex mốc giờ: 3 dạng — "16:30" | "16 giờ 30 / 16h30 / 6g30 / 7 giờ rưỡi" | giờ chữ ---
_TIME_RE = re.compile(
    r"(?P<h1>\d{1,2})\s*:\s*(?P<m1>\d{2})"
    r"|(?P<h2>\d{1,2})\s*(?:giờ|h(?=\d|\b)|g(?=\d))\s*"
    r"(?:(?P<m2>\d{1,2})\s*(?:phút)?|(?P<r2>rưỡi))?"
    r"|\b(?P<hw>mười\s+hai|mười\s+một|mười|hai|ba|bốn|tư|năm|sáu|bảy|bẩy|tám|chín|một)\s+giờ\s*"
    r"(?:(?P<m3>\d{1,2})\s*(?:phút)?|(?P<r3>rưỡi))?"
)

_WORD_HOURS = {
    "một": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5, "sáu": 6,
    "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9, "mười": 10,
    "mười một": 11, "mười hai": 12,
}

# (?!\s*đa): không nuốt "tối" trong "tối đa" (mức tối đa = max, không phải buổi tối)
_PERIOD_RE = re.compile(r"\b(sáng|trưa|chiều|tối(?!\s*đa)|đêm)\b")
_RECUR_RE = re.compile(r"\b(mỗi\s+ngày|hằng\s+ngày|hàng\s+ngày|mỗi\s+sáng|mỗi\s+trưa|mỗi\s+chiều|mỗi\s+tối|mỗi\s+đêm)\b")
_TOMORROW_RE = re.compile(r"\b(?:ngày\s+)?mai\b")
_TODAY_RE = re.compile(r"\bhôm\s+nay\b")
_RANGE_CONNECTOR_RE = re.compile(r"\b(đến|tới)\b")
_FILLER_RE = re.compile(r"\b(hẹn giúp|hẹn|đặt lịch|vào lúc|lúc)\b")


def _parse_match(m: re.Match) -> Optional[tuple]:
    """(hour, minute) từ 1 match; None nếu giá trị vô lý (giờ >23, phút >59)."""
    if m.group("h1") is not None:
        hour, minute = int(m.group("h1")), int(m.group("m1"))
    elif m.group("h2") is not None:
        hour = int(m.group("h2"))
        minute = 30 if m.group("r2") else int(m.group("m2") or 0)
    else:
        hour = _WORD_HOURS[re.sub(r"\s+", " ", m.group("hw"))]
        minute = 30 if m.group("r3") else int(m.group("m3") or 0)
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _apply_period(hour: int, period: Optional[str]) -> int:
    """Đổi giờ 12h -> 24h theo buổi trong ngày."""
    if period in ("chiều", "tối"):
        return hour + 12 if hour < 12 else hour
    if period == "đêm":
        if hour == 12:
            return 0
        return hour + 12 if 6 <= hour < 12 else hour
    if period == "trưa":
        return hour + 12 if 1 <= hour <= 3 else hour
    return hour  # sáng hoặc không nói -> giữ nguyên


def _find_period(t: str, m: re.Match, next_start: Optional[int]) -> Optional[re.Match]:
    """Tìm từ chỉ buổi quanh mốc giờ: ưu tiên NGAY SAU ("4 giờ chiều"),
    rồi mới tới TRƯỚC ("chiều nay 4 giờ"). Cửa sổ sau không vượt qua mốc giờ kế."""
    after_end = min(len(t), m.end() + 14)
    if next_start is not None:
        after_end = min(after_end, next_start)
    pm = _PERIOD_RE.search(t, m.end(), after_end)
    if pm:
        return pm
    return _PERIOD_RE.search(t, max(0, m.start() - 12), m.start())


def _tidy(s: str) -> str:
    s = _FILLER_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip(" ,.;")


def extract_schedule_times(text: str) -> Optional[dict]:
    """
    Trích mốc giờ hẹn từ câu lệnh. Trả về None nếu KHÔNG có biểu thức giờ nào
    (câu là lệnh thi hành ngay). Có giờ -> dict:
        {"start": "HH:MM", "end": "HH:MM"|None, "day_offset": 0|1,
         "recurring_daily": bool, "cleaned_text": str,
         "cleaned_head": str|None, "cleaned_tail": str|None}
    cleaned_* đã cắt bỏ cụm giờ/buổi/ngày để trích thiết bị & hành động không bị nhiễu;
    head/tail là phần trước/sau mốc kết thúc (chỉ có với khoảng "từ X đến Y").
    """
    t = text.lower()
    parsed = []
    for m in _TIME_RE.finditer(t):
        hm = _parse_match(m)
        if hm is not None:
            parsed.append((m, hm[0], hm[1]))
    if not parsed:
        return None

    spans = []  # các đoạn sẽ bị xóa khỏi cleaned_text
    start_m, start_h, start_min = parsed[0]
    spans.append(start_m.span())

    # --- Khoảng "từ X đến/tới Y": 2 mốc nối bằng đến/tới ---
    end_m = end_h = end_min = None
    connector = None
    if len(parsed) >= 2:
        connector = _RANGE_CONNECTOR_RE.search(t, parsed[0][0].end(), parsed[1][0].start())
        if connector:
            end_m, end_h, end_min = parsed[1]
            spans.append(end_m.span())
            spans.append(connector.span())
    tu = re.search(r"\btừ\s*$", t[: start_m.start()])
    if tu:
        spans.append(tu.span())

    # --- Buổi (sáng/chiều/tối/đêm) cho từng mốc ---
    start_pm = _find_period(t, start_m, end_m.start() if end_m else None)
    start_period = start_pm.group(1) if start_pm else None
    if start_pm:
        spans.append(start_pm.span())
    end_period = None
    if end_m is not None:
        end_pm = _find_period(t, end_m, None)
        end_period = end_pm.group(1) if end_pm else None
        if end_pm:
            spans.append(end_pm.span())

    start_h = _apply_period(start_h, start_period)
    if end_m is not None:
        end_h = _apply_period(end_h, end_period)
        # Chia sẻ buổi giữa 2 mốc khi 1 mốc thiếu ("từ 4 giờ đến 5 giờ chiều" = 16-17h),
        # CHỈ nhận khi kết quả giữ khoảng trong cùng ngày (end > start) — nếu không
        # thì giữ nguyên (khoảng qua đêm chủ đích, vd "11 giờ đêm đến 6 giờ").
        if start_period is None and end_period is not None:
            cand = _apply_period(start_h, end_period)
            if cand * 60 + start_min < end_h * 60 + end_min:
                start_h = cand
        elif end_period is None and start_period is not None:
            cand = _apply_period(end_h, start_period)
            if cand * 60 + end_min > start_h * 60 + start_min:
                end_h = cand

    # --- Ngày & lặp lại ---
    day_offset = 0
    recurring_daily = False
    for rm in _RECUR_RE.finditer(t):
        recurring_daily = True
        spans.append(rm.span())
    for dm in _TOMORROW_RE.finditer(t):
        day_offset = 1
        spans.append(dm.span())
    for dm in _TODAY_RE.finditer(t):
        spans.append(dm.span())

    # --- cleaned_text: che các đoạn đã dùng (giữ nguyên index để cắt head/tail) ---
    masked = list(t)
    for s, e in spans:
        for i in range(s, e):
            masked[i] = " "
    masked = "".join(masked)

    cleaned_head = cleaned_tail = None
    if end_m is not None and connector is not None:
        cleaned_head = _tidy(masked[: connector.start()])
        cleaned_tail = _tidy(masked[end_m.end():])

    return {
        "start": f"{start_h:02d}:{start_min:02d}",
        "end": f"{end_h:02d}:{end_min:02d}" if end_m is not None else None,
        "day_offset": day_offset,
        "recurring_daily": recurring_daily,
        "cleaned_text": _tidy(masked),
        "cleaned_head": cleaned_head,
        "cleaned_tail": cleaned_tail,
    }


def resolve_target_days(start_hhmm: str, day_offset: int, recurring_daily: bool,
                        now: datetime) -> tuple:
    """
    Quy đổi kết quả parse -> (days_csv, one_shot, rolled_to_tomorrow) cho ScheduleModel.
    - Lặp mỗi ngày: days rỗng, không one_shot.
    - Còn lại: lịch 1 LẦN ghim vào thứ của ngày đích; nói giờ ĐÃ QUA hôm nay
      ("hẹn 6 giờ" lúc 22h) -> tự hiểu là ngày mai (rolled=True).
    """
    if recurring_daily:
        return "", False, False
    target = now.date() + timedelta(days=day_offset)
    rolled = False
    if day_offset == 0:
        try:
            hh, mm = map(int, start_hhmm.split(":"))
        except (ValueError, AttributeError):
            hh, mm = 23, 59  # giờ hỏng -> validate phía sau sẽ chặn; không roll bừa
        if hh * 60 + mm < now.hour * 60 + now.minute:
            target += timedelta(days=1)
            rolled = True
    return str(target.weekday()), True, rolled
