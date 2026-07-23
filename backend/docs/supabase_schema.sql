-- =====================================================================
-- SmartHomeProject — Supabase Postgres schema (multi-user)
-- Chạy toàn bộ file này trong Supabase Dashboard > SQL Editor > New query.
-- Idempotent ở mức hợp lý: dùng IF NOT EXISTS / CREATE OR REPLACE.
--
-- Ghi chú thiết kế:
--  * Mọi bảng ứng dụng dùng cột user_id kiểu TEXT (= auth.users.id ép ::text).
--    Lý do: backend FastAPI dùng SQLAlchemy String + psycopg2, giữ TEXT tránh
--    lỗi so sánh uuid = varchar và tránh psycopg2 trả về đối tượng UUID.
--  * devices.id = ID thiết bị của hãng (vendor device id) — giữ nguyên như bản
--    cũ để không phải sửa local_parser / scheduler. Ở quy mô bạn bè/gia đình
--    vendor id là duy nhất nên đủ làm PK. (device khác nhau => id khác nhau.)
--  * Backend kết nối bằng connection string trực tiếp (vai trò postgres) nên
--    BỎ QUA RLS và tự scope theo user_id. RLS ở đây là hàng phòng thủ THỨ HAI,
--    phòng khi sau này frontend truy vấn thẳng Supabase.
-- =====================================================================

-- ---------------------------------------------------------------------
-- profiles: hồ sơ người dùng (tên hiển thị + vai trò). 1-1 với auth.users.
-- ---------------------------------------------------------------------
create table if not exists public.profiles (
    id           uuid primary key references auth.users(id) on delete cascade,
    email        text,
    display_name text,
    role         text not null default 'user',   -- 'user' | 'admin'
    created_at   timestamptz not null default now()
);

-- Tự tạo profile khi có user mới đăng ký.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.profiles (id, email, display_name)
    values (new.id, new.email, coalesce(new.raw_user_meta_data->>'display_name', new.email))
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------
-- vendor_accounts: tài khoản nhà cung cấp mà user đã kết nối.
--   * VeSync: credentials_encrypted chứa email/pass (Fernet) để re-login.
--   * Tuya:   tuya_uid = uid tài khoản Smart Life đã liên kết vào project.
-- ---------------------------------------------------------------------
create table if not exists public.vendor_accounts (
    id                    bigint generated always as identity primary key,
    user_id               text not null,
    brand                 text not null,            -- 'vesync' | 'tuya'
    credentials_encrypted text,                     -- Fernet token (VeSync)
    tuya_uid              text,                      -- uid Tuya (Tuya)
    label                 text default '',
    status                text default 'connected', -- connected | error
    created_at            timestamptz not null default now(),
    unique (user_id, brand)
);
create index if not exists idx_vendor_accounts_user on public.vendor_accounts(user_id);

-- ---------------------------------------------------------------------
-- devices: thiết bị của từng user. id = vendor device id (giữ như cũ).
-- ---------------------------------------------------------------------
create table if not exists public.devices (
    id         text primary key,          -- vendor device id (Tuya id / VeSync cid / slug cũ)
    user_id    text not null,
    name       text not null,
    brand      text not null,             -- tuya | vesync | rojeco
    category   text,                      -- tùy chọn: purifier | curtain | feeder ...
    is_active  boolean not null default true,
    sort_order integer not null default 0,
    created_at timestamptz not null default now()
);
create index if not exists idx_devices_user on public.devices(user_id);

-- ---------------------------------------------------------------------
-- schedules: lịch hẹn giờ, thêm user_id. Giữ brand + device_id (vendor id)
-- để scheduler gọi connector không đổi.
-- ---------------------------------------------------------------------
create table if not exists public.schedules (
    id                  bigint generated always as identity primary key,
    user_id             text not null,
    name                text default '',
    brand               text not null,
    device_id           text not null,     -- vendor device id (khớp devices.id)
    action_type         text not null,     -- on | off | mode
    action_value        text,
    time                text not null,     -- "HH:MM" Asia/Ho_Chi_Minh
    days                text default '',    -- CSV 0-6 (0=Thứ2); '' = mỗi ngày
    enabled             boolean not null default true,
    last_fired_date     text,
    end_time            text,
    end_action_type     text,
    end_action_value    text,
    last_end_fired_date text,
    one_shot            boolean not null default false
);
create index if not exists idx_schedules_user on public.schedules(user_id);

-- =====================================================================
-- Row Level Security (phòng thủ thứ hai — backend đã tự scope)
-- =====================================================================
alter table public.profiles       enable row level security;
alter table public.vendor_accounts enable row level security;
alter table public.devices         enable row level security;
alter table public.schedules       enable row level security;

-- Hàm tiện: user hiện tại có phải admin không (đọc từ profiles.role).
create or replace function public.is_admin()
returns boolean
language sql stable security definer set search_path = public
as $$
    select exists(
        select 1 from public.profiles p
        where p.id = auth.uid() and p.role = 'admin'
    );
$$;

-- profiles: user xem/sửa profile của mình; admin xem tất cả.
drop policy if exists profiles_self on public.profiles;
create policy profiles_self on public.profiles
    for select using (id = auth.uid() or public.is_admin());
drop policy if exists profiles_self_upd on public.profiles;
create policy profiles_self_upd on public.profiles
    for update using (id = auth.uid());

-- Mẫu policy owner-or-admin cho 3 bảng ứng dụng.
drop policy if exists vendor_accounts_owner on public.vendor_accounts;
create policy vendor_accounts_owner on public.vendor_accounts
    for all using (user_id = auth.uid()::text or public.is_admin())
    with check (user_id = auth.uid()::text);

drop policy if exists devices_owner on public.devices;
create policy devices_owner on public.devices
    for all using (user_id = auth.uid()::text or public.is_admin())
    with check (user_id = auth.uid()::text);

drop policy if exists schedules_owner on public.schedules;
create policy schedules_owner on public.schedules
    for all using (user_id = auth.uid()::text or public.is_admin())
    with check (user_id = auth.uid()::text);

-- =====================================================================
-- Sau khi chạy xong: đặt bạn làm admin (thay email của bạn):
--   update public.profiles set role = 'admin' where email = 'vuhp@allexceed.co.jp';
-- =====================================================================
