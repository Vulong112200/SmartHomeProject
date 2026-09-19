-- =====================================================================
-- SmartHomeProject — schema Postgres cho Supabase (Phase 1a)
--
-- Chạy file này MỘT LẦN trong Supabase SQL Editor sau khi tạo project.
-- Toàn bộ file idempotent: chạy lại nhiều lần không hỏng, không mất dữ liệu.
--
-- Phase 1a CHỈ chuyển chỗ lưu (SQLite -> Postgres). Chưa có bảng thành viên,
-- chưa có khu vực, chưa có đăng nhập — những thứ đó ở Phase 1b/2/3.
-- Shape 2 bảng dưới đây khớp đúng models/device.py và models/schedule.py.
-- =====================================================================

-- ---------------------------------------------------------------------
-- devices
-- ---------------------------------------------------------------------
create table if not exists public.devices (
    id        text primary key,              -- id thật của hãng, vd 'a32aae46a67dbe52860pza'
    name      text not null,
    brand     text not null,                 -- tuya | vesync | rojeco
    is_active boolean default true
);

-- ---------------------------------------------------------------------
-- schedules
--   time / end_time là text "HH:MM" theo giờ Asia/Ho_Chi_Minh (KHÔNG phải
--   kiểu `time` của Postgres) — scheduler.py so sánh chuỗi, đổi kiểu là hỏng.
--   end_time NULL  = lịch đơn.
--   end_time < time = khoảng QUA ĐÊM, hành động kết thúc bắn vào hôm sau.
-- ---------------------------------------------------------------------
create table if not exists public.schedules (
    id                  serial primary key,
    name                text default '',
    brand               text not null,
    device_id           text not null,
    action_type         text not null,       -- on | off | mode
    action_value        text,                -- mode: 1/2/3/auto/sleep/open/close/stop; on|off = null
    time                text not null,       -- "HH:MM"
    days                text default '',     -- CSV weekday Python (0=Thứ2..6=CN); rỗng = mỗi ngày
    enabled             boolean default true,
    last_fired_date     text,                -- "YYYY-MM-DD" — chống kích hoạt trùng trong ngày
    end_time            text,
    end_action_type     text,
    end_action_value    text,
    last_end_fired_date text,
    one_shot            boolean default false
);

-- Scheduler quét các lịch đang bật mỗi 30 giây.
create index if not exists idx_schedules_enabled on public.schedules (enabled);

-- ---------------------------------------------------------------------
-- Seed 3 thiết bị đang chạy thật
--
-- ⚠️ GIỮ NGUYÊN id. Shortcut đã pin ra màn hình chính và các slot Home Widget
-- trên điện thoại lưu theo brand + id; đổi id là hỏng cả hai mà không báo lỗi.
-- `on conflict do nothing` => chạy lại file không ghi đè tên đã sửa.
-- ---------------------------------------------------------------------
insert into public.devices (id, name, brand, is_active) values
    ('a32aae46a67dbe52860pza',           'Cửa cuốn',                 'tuya',   true),
    ('vsaq325492d4dce9e0f8eb348bb3be41', 'Lọc không khí Core 300S',  'vesync', true),
    ('a32e6ab42d076b8bb5bbrh',           'Máy cho mèo ăn tự động',   'rojeco', true)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------
-- Row Level Security — BẬT, KHÔNG viết policy
--
-- Supabase grant sẵn quyền cho role `anon` và `authenticated` trên schema
-- `public`, mà anon key thì nằm ngay trong file APK. Không bật RLS nghĩa là
-- ai giải nén được APK cũng đọc/ghi thẳng được 2 bảng này.
--
-- Bật RLS mà không có policy = deny-all cho anon/authenticated. Backend nối
-- bằng role `postgres` (connection string trong DATABASE_URL) nên BỎ QUA RLS
-- hoàn toàn và vẫn chạy bình thường. Đơn giản hơn và chặt hơn viết policy.
-- ---------------------------------------------------------------------
alter table public.devices   enable row level security;
alter table public.schedules enable row level security;

-- ---------------------------------------------------------------------
-- Kiểm tra nhanh sau khi chạy (nên thấy 3 dòng, rowsecurity = true)
-- ---------------------------------------------------------------------
-- select id, name, brand from public.devices order by brand;
-- select tablename, rowsecurity from pg_tables
--   where schemaname = 'public' and tablename in ('devices', 'schedules');
