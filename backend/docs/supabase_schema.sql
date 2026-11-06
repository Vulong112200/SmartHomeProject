-- =====================================================================
-- SmartHomeProject — schema Postgres cho Supabase (Phase 1a + 1b)
--
-- Chạy file này MỘT LẦN trong Supabase SQL Editor sau khi tạo project.
-- Toàn bộ file idempotent: chạy lại nhiều lần không hỏng, không mất dữ liệu.
--
-- Phase 1a: chuyển chỗ lưu (SQLite -> Postgres).
-- Phase 1b: thêm khu vực + thành viên + phân quyền theo khu.
-- Shape các bảng khớp đúng models/{device,schedule,member,zone}.py.
-- =====================================================================

-- ---------------------------------------------------------------------
-- zones — khu vực trong nhà (Phòng khách, Phòng ngủ, Bếp...)
-- ---------------------------------------------------------------------
create table if not exists public.zones (
    id         serial primary key,
    name       text not null,
    sort_order integer not null default 0,   -- thứ tự hiển thị
    is_shared  boolean not null default false -- khu DÙNG CHUNG: mọi thành viên thấy, không cần cấp
);

alter table public.zones add column if not exists is_shared boolean not null default false;

-- ---------------------------------------------------------------------
-- members — thành viên trong nhà
--   user_id = auth.users.id của Supabase, lưu dạng text để SQLite dùng chung.
--   role:   owner | adult | kid | guest
--   status: pending | active | blocked  (người lạ lần đầu -> guest/pending)
-- ---------------------------------------------------------------------
create table if not exists public.members (
    user_id      text primary key,
    email        text not null default '',
    display_name text not null default '',
    role         text not null default 'guest',
    status       text not null default 'pending',
    avatar_color text,                        -- "#RRGGBB" chọn ở màn Hồ sơ; NULL = màu tự động
    sort_order   jsonb                        -- ["device-id", ...] thứ tự Dashboard của người này; NULL = mặc định
);

alter table public.members add column if not exists avatar_color text;
alter table public.members add column if not exists sort_order jsonb;

-- ---------------------------------------------------------------------
-- member_zone_access — grant: thành viên được dùng khu nào
--   Chỉ áp dụng cho kid/guest; owner/adult thấy mọi khu theo luật vai nên
--   KHÔNG có hàng nào ở đây.
-- ---------------------------------------------------------------------
create table if not exists public.member_zone_access (
    user_id text    not null references public.members(user_id) on delete cascade,
    zone_id integer not null references public.zones(id)        on delete cascade,
    primary key (user_id, zone_id)
);

-- ---------------------------------------------------------------------
-- devices
--   zone_id NULL = "hộp thư đến": thiết bị vừa import chưa gán phòng, chỉ
--   owner/adult thấy. Điều này rơi ra miễn phí từ INNER JOIN khi lọc theo khu.
--   on delete set null: xóa khu thì thiết bị về hộp thư đến, không xóa theo.
-- ---------------------------------------------------------------------
create table if not exists public.devices (
    id        text primary key,              -- id thật của hãng, vd 'a32aae46a67dbe52860pza'
    name      text not null,
    brand     text not null,                 -- tuya | vesync | rojeco
    is_active boolean default true,
    zone_id   integer references public.zones(id) on delete set null,
    category  text                           -- purifier | curtain | feeder | switch (NULL = suy từ tên)
);

-- Nếu bảng devices đã tồn tại từ Phase 1a thì thêm cột mới (idempotent).
alter table public.devices add column if not exists zone_id  integer references public.zones(id) on delete set null;
alter table public.devices add column if not exists category text;

create index if not exists idx_devices_zone on public.devices (zone_id);

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
    one_shot            boolean default false,
    created_by          text     -- chỉ để audit + chặn kid sửa lịch người khác
);

alter table public.schedules add column if not exists created_by text;

-- Scheduler quét các lịch đang bật mỗi 30 giây.
create index if not exists idx_schedules_enabled on public.schedules (enabled);

-- ---------------------------------------------------------------------
-- scenes — kịch bản: 1 nút chạy nhiều hành động
--   actions = JSON text [{"device_id","action_type","action_value"}] đã chuẩn
--   hóa theo loại thiết bị lúc lưu (services/device_actions.py).
--   conditions = JSON text {"operator","items"} (NULL = không điều kiện) —
--   services/scene_condition_engine.py. Backend tự ALTER thêm cột lúc boot.
-- ---------------------------------------------------------------------
create table if not exists public.scenes (
    id         serial primary key,
    name       text not null,
    icon       text,
    sort_order integer not null default 0,
    actions    text not null default '[]',
    created_by text,
    conditions text
);
alter table public.scenes add column if not exists conditions text;

-- ---------------------------------------------------------------------
-- floor_plans — sơ đồ mặt bằng 2D (1 hàng duy nhất, id = 1)
-- Backend TỰ TẠO bảng này lúc boot (create_all); khối này chỉ để tham khảo.
-- layout = JSON text {rooms, doors, devices} theo MÉT, đã làm sạch bởi
-- services/floor_plan.sanitize_layout. Không có hàng = bố cục mặc định.
-- ---------------------------------------------------------------------
create table if not exists public.floor_plans (
    id            integer primary key,
    layout        text not null,
    updated_by    text,
    updated_at_ms bigint
);

-- ---------------------------------------------------------------------
-- command_logs — lịch sử lệnh điều khiển + sự kiện ngoài app (nút vật lý...)
-- Backend TỰ TẠO bảng này lúc boot (create_all); khối này chỉ để tham khảo.
-- at_ms = epoch mili-giây UTC. ext_id chống trùng khi đồng bộ nhật ký Tuya.
-- ---------------------------------------------------------------------
create table if not exists public.command_logs (
    id           serial primary key,
    at_ms        bigint  not null,
    device_id    text    not null,
    device_name  text,
    action_type  text,
    action_value text,
    action_label text    not null,
    source       text    not null,
    user_id      text,
    user_name    text,
    success      boolean,
    detail       text,
    ext_id       text unique
);
create index if not exists ix_command_logs_at_ms     on public.command_logs (at_ms);
create index if not exists ix_command_logs_device_id on public.command_logs (device_id);

-- ---------------------------------------------------------------------
-- Seed 3 thiết bị đang chạy thật
--
-- ⚠️ GIỮ NGUYÊN id. Shortcut đã pin ra màn hình chính và các slot Home Widget
-- trên điện thoại lưu theo brand + id; đổi id là hỏng cả hai mà không báo lỗi.
-- `on conflict do nothing` => chạy lại file không ghi đè tên đã sửa.
-- ---------------------------------------------------------------------
insert into public.devices (id, name, brand, is_active, category) values
    ('a32aae46a67dbe52860pza',           'Cửa cuốn',                 'tuya',   true, 'curtain'),
    ('vsaq325492d4dce9e0f8eb348bb3be41', 'Lọc không khí Core 300S',  'vesync', true, 'purifier'),
    ('a32e6ab42d076b8bb5bbrh',           'Máy cho mèo ăn tự động',   'rojeco', true, 'feeder')
on conflict (id) do nothing;

-- DB đã seed trước khi có category: điền loại cho 3 thiết bị gốc. Chỉ đụng
-- hàng còn NULL nên không ghi đè loại chủ nhà đã chọn.
update public.devices d
set category = v.category
from (values
    ('a32aae46a67dbe52860pza',           'curtain'),
    ('vsaq325492d4dce9e0f8eb348bb3be41', 'purifier'),
    ('a32e6ab42d076b8bb5bbrh',           'feeder')
) as v(id, category)
where d.id = v.id and d.category is null;

-- Khu mặc định: nếu chưa chia phòng thì mọi thiết bị nằm ở "hộp thư đến"
-- (zone_id NULL) và không cấp quyền cho kid/guest được. Tạo sẵn một khu 'Nhà'
-- rồi gán thiết bị chưa phân khu vào đó. Chủ nhà chia phòng thật sau ở app.
insert into public.zones (name, sort_order)
select 'Nhà', 0
where not exists (select 1 from public.zones);

update public.devices
set zone_id = (select id from public.zones order by id limit 1)
where zone_id is null;

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
alter table public.devices            enable row level security;
alter table public.schedules          enable row level security;
alter table public.zones              enable row level security;
alter table public.members            enable row level security;
alter table public.member_zone_access enable row level security;
alter table public.scenes             enable row level security;
alter table public.command_logs       enable row level security;
alter table public.floor_plans        enable row level security;

-- ---------------------------------------------------------------------
-- Kiểm tra nhanh sau khi chạy (nên thấy 3 dòng, rowsecurity = true)
-- ---------------------------------------------------------------------
-- select d.id, d.name, d.brand, z.name as zone
--   from public.devices d left join public.zones z on z.id = d.zone_id
--   order by d.brand;
-- select tablename, rowsecurity from pg_tables
--   where schemaname = 'public'
--     and tablename in ('devices','schedules','zones','members','member_zone_access');
