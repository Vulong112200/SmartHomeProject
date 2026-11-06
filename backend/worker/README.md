# Worker Hẹn giờ tại nhà

Tiến trình Python **độc lập** (không cần FastAPI/uvicorn) chạy 24/7 trên máy tính hoặc
Raspberry Pi ở nhà, bắn các lịch hẹn giờ từ **cùng database Postgres Supabase** với backend
trên Render. Mục đích: lịch không còn phụ thuộc việc Render free-tier có đang thức hay không.

```
 App Flutter ──HTTP──▶ Render (FastAPI) ──┐                 ┌──▶ Tuya / VeSync / Rojeco cloud
   (tạo/sửa lịch)      scheduler "api"    ├──▶ Supabase ◀──┤
                                          │   Postgres      │
              Raspberry Pi ── python -m worker ─────────────┘
                              scheduler "worker"
```

Worker **không** có bản sao logic riêng: nó chạy đúng bộ máy `app/services/scheduler.py`
(`ScheduleEngine`) mà backend dùng, cùng connector (`register_default_connectors`), cùng
`normalize_action()`, cùng luật quyền `household.scheduler_target_device`, cùng
`command_log.record` (lịch sử nguồn `schedule`). Chỉ phần vỏ nằm trong `worker/`.

---

## 1. Chống bắn trùng — vì sao chạy 2 nơi cùng lúc vẫn an toàn

Mỗi lần một lịch đến hạn (1 *occurrence* = lịch × start/end × ngày-giờ hẹn) chỉ **một**
tiến trình được gửi lệnh, dù có bao nhiêu worker/Render đang chạy:

1. **Claim nguyên tử (compare-and-set).** Một câu `UPDATE schedules SET last_fired_date = hôm nay
   WHERE id = … AND enabled AND last_fired_date <> hôm nay AND time/days/thiết bị/hành động = lúc đọc`.
   Postgres khóa hàng khi UPDATE; tiến trình thứ hai chờ, đánh giá lại WHERE, thấy đã là hôm nay
   → 0 hàng → bỏ qua. Lịch vừa bị sửa trên app cũng → 0 hàng (không bắn lệnh cũ).
2. **Chốt thứ hai:** cùng transaction, `INSERT schedule_runs` với
   `UNIQUE(schedule_id, part, occurrence)`. Một trong hai hụt → rollback cả hai.
3. **Đánh dấu trước, gửi sau** (giữ nguyên quy tắc cũ): lệnh lỗi không tự bắn lại ở tick sau.

Đã cân nhắc và **không** dùng advisory lock của Postgres làm cơ chế chính: qua Supabase pooler
chế độ transaction, khóa phiên không đáng tin; một khóa rò = không tiến trình nào bắn lịch nào;
và khóa "leader" không bảo vệ được đoạn gửi lệnh khi leader mất DB mà vẫn có Internet. Cũng không
dùng `SELECT … FOR UPDATE` giữ suốt lúc gửi: phải giữ transaction mở 15–60s qua pooler.
Claim theo từng occurrence đúng trên mọi loại kết nối, cả SQLite (dev).

## 2. Phục hồi khi crash / mất kết nối

Mỗi lần chạy có vòng đời trong `schedule_runs.status`:

```
claimed ──▶ sending ──▶ success
   │           │    └─▶ retry ──(sau 30s)──▶ sending … ──▶ failed
   │           └─ kẹt > 90s (tiến trình chết / mất mạng khi đang gửi)
   └─ kẹt > 90s (chết TRƯỚC khi gửi)
rejected = không gửi (thiết bị đã xóa / hành động sai loại)   abandoned = bỏ, có ghi lịch sử
```

- `claimed` kẹt = **chắc chắn chưa gửi** → tiến trình còn sống (hoặc chính worker sau khi khởi
  động lại) giành lại bằng compare-and-set rồi gửi, nếu còn trong cửa sổ của loại thiết bị.
- `sending` kẹt = **không biết** lệnh đã tới thiết bị chưa → chỉ gửi lại hành động lặp lại vô hại.
- Thiết bị trả lỗi / timeout 60s → `retry` theo bảng dưới.

| Loại | Gửi lại khi không chắc? | Cửa sổ (từ giờ hẹn) | Tối đa |
|---|---|---|---|
| Máy lọc, công tắc (máy bơm) | Có | 10 phút | 3 lần |
| Cửa cuốn | Có (mở/đóng/dừng lặp lại vô hại) | **3 phút** — đóng cửa trễ có thể sập xuống lúc có người vừa mở ra | 2 lần |
| Máy cho ăn | **Không bao giờ** — cho ăn 2 lần tệ hơn lỡ 1 bữa | 10 phút (chỉ khi chắc chắn chưa gửi) | 1 lần |
| Loại chưa rõ | Không | 10 phút | 1 lần |

Mọi lần gửi (kể cả thất bại, kể cả "không xác nhận được") đều có dòng trong Lịch sử điều khiển
với `success=false` — **không bao giờ** ghi thành công khi chưa chắc.

Worker lấy **giờ của Postgres** (`clock_timestamp()`) làm đồng hồ: Raspberry Pi không có pin RTC,
lúc mới khởi động giờ có thể sai tới khi NTP đồng bộ — không ảnh hưởng giờ bắn lịch.

## 3. Cài đặt

Cần: Python **3.11+** (khuyên 3.13 như dev; Raspberry Pi OS **64-bit** Bookworm có sẵn 3.11 —
bản 32-bit thiếu wheel cho vài gói như `pydantic_core`, `cryptography`), `git`.

```bash
# Raspberry Pi / Linux
sudo apt update && sudo apt install -y git python3-venv
cd ~ && git clone <url-repo> SmartHomeProject && cd SmartHomeProject
git checkout release/prod-ready          # hoặc main sau khi đã fast-forward
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

Windows (PowerShell): giống dev — `python -m venv .venv` rồi
`.venv\Scripts\pip install -r backend\requirements.txt`.

Chỉ dùng **một** file requirements (`backend/requirements.txt`) cho cả backend lẫn worker —
không tạo bản sao (bài học sự cố `PyJWT` khi 2 file lệch nhau).

## 4. Cấu hình `.env`

```bash
cp backend/worker/deploy/worker.env.example backend/worker/.env
chmod 600 backend/worker/.env      # chỉ user chạy worker đọc được
nano backend/worker/.env
```

Worker tìm file theo thứ tự: `--env-file` → `WORKER_ENV_FILE` → `backend/worker/.env` →
`backend/.env`. Biến môi trường thật luôn thắng file. `.env` đã nằm trong `.gitignore`.

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `WORKER_DATABASE_URL` hoặc `DATABASE_URL` | ✅ | Chuỗi **Session pooler** (cổng 5432) của Supabase. Thiếu → worker từ chối chạy (không bao giờ rơi về SQLite âm thầm) |
| `TUYA_ACCESS_ID/KEY/API_ENDPOINT`, `VESYNC_EMAIL/PASSWORD` | ✅ | Như backend |
| `WORKER_ID` | | Tên hiện ở `status` (mặc định hostname) |
| `WORKER_LOG_FILE` | | Thêm log file xoay vòng 5 MB × 5 (nên đặt trên Windows) |
| `WORKER_TICK_SECONDS` | | 5–55, mặc định 30 (cửa sổ kích hoạt 120s) |
| `WORKER_ALLOW_SQLITE=1` | | Chỉ dev/test |

Không cần `OPENROUTER_API_KEY`, `SUPABASE_*`, `APP_TOKEN_SECRET`.

### Quyền database tối thiểu (khuyên dùng)

File `.env` trên Pi mà dùng role `postgres` thì mất Pi = mất toàn quyền DB. Chạy
[`deploy/worker_role.sql`](deploy/worker_role.sql) trong Supabase → SQL Editor (đổi mật khẩu
trong file trước), rồi dùng user `smarthome_worker.<project-ref>` trong `WORKER_DATABASE_URL`.
Role này chỉ đọc `devices`, đọc + sửa đúng 3 cột của `schedules`, ghi `schedule_runs` /
`scheduler_heartbeats`, thêm `command_logs`. Có policy RLS riêng cho role này; `anon` /
`authenticated` (khóa nằm trong APK) vẫn bị chặn như cũ.

## 5. Chạy thử

Từ thư mục `backend/`:

```bash
../.venv/bin/python -m worker status   # CHỈ ĐỌC: DB, schema, đồng hồ, nhịp tim, lịch sẽ bị từ chối
../.venv/bin/python -m worker once     # 1 tick thật rồi thoát (bắn lịch nếu đang đến hạn!)
../.venv/bin/python -m worker          # chạy liên tục, Ctrl+C để dừng
```

`status` liệt kê lịch nào sẽ **bị từ chối** khi đến giờ (thiết bị đã xóa, hoặc hành động sai loại
— vd lịch "Bật" cho cửa cuốn). Scheduler mới chuẩn hóa hành động qua `normalize_action()` trước
khi gửi; scheduler cũ thì không. Sửa các lịch đó trong tab Hẹn giờ trước khi chuyển đổi.

Thiếu bảng (`schedule_runs`, `scheduler_heartbeats`) → worker **không tự tạo** (chạy được bằng
role quyền hẹp), báo rõ và chờ. Bảng được backend mới tạo lúc boot, hoặc chạy
`backend/docs/supabase_schema.sql`.

## 6. Chạy nền 24/7, tự khởi động lại

### Raspberry Pi / Linux — systemd

```bash
sudo cp backend/worker/deploy/smarthome-worker.service /etc/systemd/system/
sudo nano /etc/systemd/system/smarthome-worker.service   # sửa User + đường dẫn
sudo systemctl daemon-reload
sudo systemctl enable --now smarthome-worker              # bật + tự chạy khi reboot
systemctl status smarthome-worker
```

`Restart=always` khởi động lại sau 10s nếu tiến trình chết; `StartLimitIntervalSec=0` không bao
giờ bỏ cuộc. Dừng (`systemctl stop`, reboot) gửi SIGTERM: worker làm **xong tick đang chạy**
(không cắt ngang lệnh cửa dở dang), ghi nhịp tim `stopped` rồi thoát.

### Windows — Task Scheduler

Máy phải **không ngủ** (Settings → Power → Sleep: Never). PowerShell quyền Admin:

```powershell
$root = "D:\Tools\SmartHomeProject"
$action = New-ScheduledTaskAction -Execute "$root\.venv\Scripts\python.exe" -Argument "-m worker" -WorkingDirectory "$root\backend"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "SmartHome Worker" -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM" -RunLevel Highest
Start-ScheduledTask -TaskName "SmartHome Worker"
```

Đặt `WORKER_LOG_FILE=worker/logs/worker.log` (task chạy không có cửa sổ). "End task" trên
Windows là giết cứng: lần chạy đang gửi (nếu có) được phục hồi theo bảng ở mục 2.

## 7. Log và kiểm tra worker còn sống

- Linux: `journalctl -u smarthome-worker -f` (theo dõi), `journalctl -u smarthome-worker --since today`.
- File: `backend/worker/logs/worker.log` nếu đặt `WORKER_LOG_FILE`.
- **Từ bất kỳ máy nào có DATABASE_URL** (kể cả PC dev): `python -m worker status`. Mã thoát
  `0` = có worker đang chạy (nhịp tim < 90s), `1` = không có, `2` = không đọc được DB — dùng
  được trong script giám sát/cron. Dòng nhịp tim có `v=<commit>` để biết máy ở nhà chạy bản nào.
- Lỗi được log lần đầu và mỗi ~10 phút nếu còn lỗi (không xả log mỗi 30s); khi hết lỗi log
  `Scheduler KHÔI PHỤC sau N tick lỗi`.

## 8. Khi mất Internet

| Tình huống | Hành vi |
|---|---|
| Pi khởi động khi chưa có mạng | Chờ DB với backoff 5s→60s, không thoát; có mạng là chạy |
| Mất mạng giữa chừng | Tick lỗi, log; tick sau tự nối lại (`pool_pre_ping`, TCP keepalive, timeout 10s) |
| Mạng về trong 120s sau giờ hẹn | Vẫn bắn bình thường |
| Mạng về muộn hơn | Lịch lặp: bỏ lần đó (không bắn bù muộn — cửa cuốn bắn trễ nguy hiểm). Lịch 1 lần: tự tắt + log. Nếu Render để `SCHEDULER_ENABLED=auto`, Render **tiếp quản** sau 90s không thấy nhịp tim nên lịch vẫn chạy đúng giờ |
| Mất mạng khi đang gửi lệnh | Lần chạy kẹt `sending` → phục hồi theo bảng mục 2 |
| Supabase OK nhưng cloud Tuya/VeSync lỗi | Thiết bị "không nhận lệnh" → `retry` theo bảng mục 2 |

## 9. Cập nhật phiên bản

```bash
cd ~/SmartHomeProject && git pull
.venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart smarthome-worker
cd backend && ../.venv/bin/python -m worker status   # dòng nhịp tim mới có v=<commit mới>
```

Restart **không** gây gửi lặp: mọi quyết định chống trùng nằm trong DB, không trong RAM; tiến
trình mới có id mới và chỉ giành lại lần chạy kẹt sau khi hết hạn thuê 90s.
Nếu bản mới cần bảng/cột mới: deploy backend lên Render **trước**, worker sau.

## 10. Chuyển đổi production an toàn

> ⚠️ Scheduler đang chạy trên production (`main` = `9ae9de6`) là bản CŨ: đọc rồi mới ghi
> `last_fired_date` (không nguyên tử) và **không có** `SCHEDULER_ENABLED` — không tắt được nếu
> không deploy. Vì vậy **không chạy worker trước khi Render chạy code mới**.

1. **Deploy backend mới lên Render**, để `SCHEDULER_ENABLED` trống (= `1`). Lúc boot,
   `create_all` tạo `schedule_runs` + `scheduler_heartbeats`; scheduler trên Render giờ claim
   nguyên tử. Người dùng không thấy gì khác. Kiểm: log boot có `chế độ on`; `python -m worker status`
   (từ PC) thấy dòng nhịp tim `api running`. ⚠️ Nhánh `release/prod-ready` còn mang theo các tính
   năng chưa lên production (sơ đồ mặt bằng, điều kiện kịch bản, sắp xếp thiết bị) — fast-forward
   `main` là deploy tất cả.
2. *(Khuyên)* Tạo role quyền hẹp (`deploy/worker_role.sql`).
3. **Chạy `python -m worker status`** trên máy ở nhà → sửa các lịch bị báo "sẽ KHÔNG gửi".
4. **Bật worker** (mục 6). Giai đoạn song song: Render và worker cùng chạy (`1`); mỗi lần đến hạn
   chỉ một bên thắng. Theo dõi 2–3 ngày: `status` → cột worker của "lần chạy gần nhất" có
   `worker:…`, không có dòng trùng occurrence, Lịch sử trong app đúng 1 dòng mỗi lần hẹn. Kiểm
   riêng máy lọc VeSync: worker và Render cùng đăng nhập 1 tài khoản — xem log có lỗi đăng nhập
   lặp lại không.
5. **Đặt `SCHEDULER_ENABLED=auto` trên Render** (Dashboard → Environment, redeploy). Worker là
   chính; Render đứng chờ và tự tiếp quản khi worker im lặng > 90s (Pi mất điện/mất mạng).
   Đây là trạng thái khuyên dùng. Đặt `0` nếu muốn chỉ chạy ở nhà (mất dự phòng).

**Quay lui:** `sudo systemctl stop smarthome-worker` → nhịp tim `stopped` → Render (`auto`) tiếp
quản ngay ở tick kế. Hoặc xóa `SCHEDULER_ENABLED` trên Render để về như bước 1. Scheduler trong
FastAPI **không bị xóa** — nó là cùng bộ máy, chỉ bật/tắt bằng biến.

## 11. Giới hạn đã biết

- Worker không có kết nối `/ws` tới app. Sau khi worker bắn lịch, app thấy trạng thái mới qua
  watcher 15s của Render / poll 6s của app (cache trạng thái 3s trên Render không bị xóa từ xa).
  Lịch sử điều khiển vẫn ghi đầy đủ ngay.
- Phát hiện "thay đổi ngoài app" của máy lọc VeSync trên Render đọc thêm `command_logs` trong DB,
  nên lệnh của worker không bị ghi nhầm thành "ngoài app".
- Thời điểm `at_ms` của dòng lịch sử theo giờ máy chạy worker (giờ bắn lịch thì theo giờ DB) —
  giữ NTP bật trên Pi (mặc định có).
- Chưa kiểm thử trên Postgres thật / Raspberry Pi thật trong CI (test chạy SQLite). Postgres dùng
  cùng câu UPDATE có điều kiện + UNIQUE, là cơ chế chuẩn của Postgres; xác nhận ở bước 4.
