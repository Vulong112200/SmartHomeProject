"""
Worker Hẹn giờ tại nhà — tiến trình Python độc lập (KHÔNG cần FastAPI/uvicorn)
chạy 24/7 trên máy tính hoặc Raspberry Pi, bắn lịch hẹn từ cùng database
Postgres (Supabase) với backend trên Render.

Dùng CHUNG với backend: bộ máy `app.services.scheduler.ScheduleEngine`, các
connector (`register_default_connectors`), `normalize_action`, luật quyền
`household.scheduler_target_device`, ghi lịch sử `command_log.record`.
Chỉ phần "vỏ" nằm ở đây: cấu hình, kết nối DB riêng, vòng lặp, tín hiệu dừng.

Chạy (từ thư mục backend/):
    python -m worker            # chạy liên tục
    python -m worker once       # 1 tick rồi thoát (kiểm thử)
    python -m worker status     # sức khỏe: DB, nhịp tim, lần chạy gần đây

Hướng dẫn vận hành: backend/worker/README.md
"""
