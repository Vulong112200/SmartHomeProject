# Thiết lập Supabase cho SmartHomeProject (multi-user)

Các bước 1 lần để chuyển từ SQLite cá nhân sang Supabase đa người dùng.

## 1. Tạo project Supabase
1. Vào https://supabase.com → New project. Chọn region gần (Singapore).
2. Đặt **Database password** (nhớ kỹ — dùng trong `DATABASE_URL`).

## 2. Chạy schema
1. Dashboard > **SQL Editor** > New query.
2. Dán toàn bộ nội dung `backend/docs/supabase_schema.sql` → **Run**.
3. Đặt bạn làm admin (sửa đúng email của bạn):
   ```sql
   update public.profiles set role = 'admin' where email = 'vuhp@allexceed.co.jp';
   ```
   (Profile chỉ được tạo SAU khi bạn đăng ký tài khoản lần đầu ở bước 5 — nên chạy lệnh này sau khi đã đăng nhập 1 lần.)

## 3. Lấy các khóa
- **Settings > Database > Connection string > URI** (dùng **Session pooler**, port 5432, hoặc **Transaction pooler** 6543): đây là `DATABASE_URL`. Đổi tiền tố thành `postgresql+psycopg2://...` và thêm `?sslmode=require`.
  Ví dụ: `postgresql+psycopg2://postgres.xxxx:PASSWORD@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require`
- **Settings > API**:
  - `Project URL` → `SUPABASE_URL` (dùng cho frontend).
  - `anon public` key → `SUPABASE_ANON_KEY` (dùng cho frontend).
  - **JWT Secret** (Settings > API > JWT Settings — dùng *legacy JWT secret*, HS256) → `SUPABASE_JWT_SECRET` (backend verify token).

## 4. Sinh khóa mã hóa credential (Fernet)
Chạy 1 lần, lưu kết quả vào `FERNET_KEY`:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 5. Điền `.env` (xem `.env.example`)
```
DATABASE_URL=postgresql+psycopg2://...:...@...pooler.supabase.com:5432/postgres?sslmode=require
SUPABASE_JWT_SECRET=...          # legacy JWT secret (HS256)
FERNET_KEY=...                   # từ bước 4
ADMIN_EMAILS=vuhp@allexceed.co.jp
# Tuya project (giữ nguyên — dùng chung 1 project cho mọi user)
TUYA_ACCESS_ID=...
TUYA_ACCESS_KEY=...
TUYA_API_ENDPOINT=https://openapi-sg.iotbing.com/
TUYA_APP_SCHEMA=...              # schema app đã liên kết trong Tuya IoT (cho Tuya discovery)
OPENROUTER_API_KEY=...
```
Trên Render: set các biến này trong **Dashboard > Environment**.

> **Local dev**: nếu KHÔNG đặt `DATABASE_URL`, backend tự dùng SQLite (`smarthome.db`) như cũ — tiện chạy/test offline. Auth vẫn cần `SUPABASE_JWT_SECRET` để verify token (hoặc đặt `AUTH_DISABLED=1` để bỏ auth khi test local).

## 6. Kích hoạt Auth
- Dashboard > **Authentication > Providers**: bật **Email** (bạn bè/gia đình đủ dùng). Tùy chọn tắt "Confirm email" để đăng ký nhanh.
- (Tùy chọn) bật **Google** sau này.

## Migrate dữ liệu cá nhân hiện có
Dữ liệu cũ nằm trong `backend/smarthome.db` (SQLite). Sau khi có Supabase + đăng ký tài khoản admin của bạn, chèn lại thiết bị của bạn kèm `user_id` = id tài khoản admin (lấy từ `select id from auth.users where email='...'`). Hoặc đơn giản: dùng luồng "Thêm thiết bị" trong app để khám phá lại (VeSync tự động; Tuya liên kết QR).
