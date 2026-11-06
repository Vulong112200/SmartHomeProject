# backend/app/models/schedule_run.py
"""
Nhật ký thực thi lịch hẹn + nhịp tim của các tiến trình chạy lịch.

`schedule_runs` — MỖI LẦN một lịch đến hạn (1 "occurrence" = lịch × phần
start/end × ngày-giờ hẹn) có đúng 1 hàng. Hàng được tạo TRONG CÙNG transaction
với lệnh UPDATE có điều kiện (compare-and-set) đánh dấu `last_fired_date` — nên
"ai tạo được hàng này thì người đó được gửi lệnh". UNIQUE trên occurrence là
chốt thứ hai: hai tiến trình (Render + worker tại nhà, hay 2 worker) không thể
cùng giữ một occurrence.

Vòng đời trạng thái (xem services/scheduler.py):
    claimed  -> sending -> success | retry | failed
    claimed/sending quá hạn thuê (tiến trình chết) -> phục hồi: gửi lại hoặc abandoned
    rejected = không gửi vì thiết bị không còn / hành động không hợp lệ.
`claimed` = CHẮC CHẮN chưa gửi gì. `sending` = có thể đã tới thiết bị — chỉ
hành động lặp lại vô hại (bật/tắt/chế độ/cửa) mới được gửi lại; máy cho ăn
KHÔNG BAO GIỜ gửi lại (cho ăn 2 lần tệ hơn bỏ lỡ 1 bữa).

Không có FK tới `schedules`: xóa lịch không bị chặn và nhật ký vẫn giữ lại.

`scheduler_heartbeats` — mỗi tiến trình chạy lịch (vòng lặp trong FastAPI = role
`api`, worker tại nhà = role `worker`) ghi nhịp tim mỗi tick. Dùng để:
  - Render ở chế độ SCHEDULER_ENABLED=auto đứng chờ khi worker còn sống;
  - `python -m worker status` cho biết worker còn sống không, từ bất kỳ máy nào.
"""
from sqlalchemy import BigInteger, Column, Integer, String, UniqueConstraint

from app.core.database import Base

# Trạng thái 1 lần chạy.
RUN_CLAIMED = "claimed"      # đã giành quyền, CHƯA gửi gì
RUN_SENDING = "sending"      # đang gửi — kết quả chưa biết
RUN_SUCCESS = "success"
RUN_RETRY = "retry"          # lần gửi không xác nhận được, sẽ thử lại sau backoff
RUN_FAILED = "failed"        # hết lượt thử / hết cửa sổ — dừng
RUN_REJECTED = "rejected"    # không gửi: thiết bị mất / hành động sai loại
RUN_ABANDONED = "abandoned"  # tiến trình chết giữa chừng và không được gửi lại

RUN_OPEN = (RUN_CLAIMED, RUN_SENDING, RUN_RETRY)


class ScheduleRunModel(Base):
    __tablename__ = "schedule_runs"
    __table_args__ = (
        UniqueConstraint("schedule_id", "part", "occurrence", name="uq_schedule_runs_occurrence"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_id = Column(Integer, nullable=False, index=True)
    part = Column(String, nullable=False)               # start | end
    occurrence = Column(String, nullable=False)         # "YYYY-MM-DDTHH:MM" giờ VN của mốc hẹn
    due_at_ms = Column(BigInteger, nullable=False)      # mốc hẹn (epoch ms) — tính cửa sổ thử lại
    label = Column(String, nullable=True)               # tên lịch lúc chạy (ẢNH CHỤP, cho lịch sử)
    device_id = Column(String, nullable=False)
    brand = Column(String, nullable=True)               # hãng lấy từ bảng devices lúc gửi
    action_type = Column(String, nullable=False)
    action_value = Column(String, nullable=True)
    status = Column(String, nullable=False, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    worker_id = Column(String, nullable=True)           # tiến trình đang giữ/đã giữ lần chạy
    claimed_at_ms = Column(BigInteger, nullable=False)
    updated_at_ms = Column(BigInteger, nullable=False, index=True)
    detail = Column(String, nullable=True)


class SchedulerHeartbeatModel(Base):
    __tablename__ = "scheduler_heartbeats"

    worker_id = Column(String, primary_key=True)        # duy nhất theo TIẾN TRÌNH (host#pid-xxxx)
    role = Column(String, nullable=False)               # api | worker
    host = Column(String, nullable=True)
    pid = Column(Integer, nullable=True)
    state = Column(String, nullable=False)              # running | standby | stopped | error
    started_at_ms = Column(BigInteger, nullable=False)
    last_seen_ms = Column(BigInteger, nullable=False, index=True)
    detail = Column(String, nullable=True)
