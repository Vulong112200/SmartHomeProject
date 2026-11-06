-- =====================================================================
-- Role Postgres QUYỀN TỐI THIỂU cho worker Hẹn giờ tại nhà (Supabase).
--
-- Vì sao: máy ở nhà (Raspberry Pi) giữ chuỗi kết nối DB trong file .env.
-- Dùng role `postgres` thì lộ file = lộ toàn quyền DB (members, xóa bảng...).
-- Role này chỉ làm được đúng việc của worker:
--   devices              : đọc
--   schedules            : đọc + sửa 3 cột last_fired_date / last_end_fired_date / enabled
--   schedule_runs        : đọc/ghi/xóa (nhật ký chạy lịch)
--   scheduler_heartbeats : đọc/ghi/xóa (nhịp tim)
--   command_logs         : đọc + thêm (ghi lịch sử; INSERT ... RETURNING cần SELECT)
--
-- Chạy trong Supabase → SQL Editor, SAU KHI backend mới đã boot ít nhất 1 lần
-- (đã có bảng schedule_runs / scheduler_heartbeats) hoặc sau supabase_schema.sql.
-- Đổi mật khẩu bên dưới — KHÔNG commit mật khẩu thật. Chạy lại được (idempotent).
--
-- Kết nối qua Session pooler: user = smarthome_worker.<project-ref>, cổng 5432.
-- =====================================================================

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'smarthome_worker') then
    create role smarthome_worker with login password 'DOI-MAT-KHAU-NAY';
  end if;
end $$;
-- Đổi mật khẩu sau này: alter role smarthome_worker with password '...';

grant usage on schema public to smarthome_worker;

grant select                         on public.devices              to smarthome_worker;
grant select                         on public.schedules            to smarthome_worker;
grant update (last_fired_date, last_end_fired_date, enabled)
                                     on public.schedules            to smarthome_worker;
grant select, insert, update, delete on public.schedule_runs        to smarthome_worker;
grant select, insert, update, delete on public.scheduler_heartbeats to smarthome_worker;
grant select, insert                 on public.command_logs         to smarthome_worker;
grant usage on sequence public.schedule_runs_id_seq, public.command_logs_id_seq to smarthome_worker;

-- RLS: các bảng đang BẬT RLS không policy (deny-all cho anon/authenticated).
-- Role này không phải owner/bypassrls nên cần policy — CHỈ cho role này,
-- anon/authenticated (khóa trong APK) vẫn bị chặn như cũ.
drop policy if exists worker_select on public.devices;
create policy worker_select on public.devices for select to smarthome_worker using (true);

drop policy if exists worker_select on public.schedules;
create policy worker_select on public.schedules for select to smarthome_worker using (true);
drop policy if exists worker_update on public.schedules;
create policy worker_update on public.schedules for update to smarthome_worker using (true) with check (true);

drop policy if exists worker_all on public.schedule_runs;
create policy worker_all on public.schedule_runs for all to smarthome_worker using (true) with check (true);

drop policy if exists worker_all on public.scheduler_heartbeats;
create policy worker_all on public.scheduler_heartbeats for all to smarthome_worker using (true) with check (true);

drop policy if exists worker_select on public.command_logs;
create policy worker_select on public.command_logs for select to smarthome_worker using (true);
drop policy if exists worker_insert on public.command_logs;
create policy worker_insert on public.command_logs for insert to smarthome_worker with check (true);

-- Kiểm tra: đăng nhập bằng role này rồi chạy `python -m worker status`.
-- Thu hồi toàn bộ: xóa 7 policy ở trên (drop policy ... on ...), rồi
--   drop owned by smarthome_worker; drop role smarthome_worker;
-- Tạm khóa nhanh (không xóa gì): alter role smarthome_worker nologin;
