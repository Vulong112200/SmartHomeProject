# CLAUDE.md — SmartHomeProject

> Tài liệu điều hướng cho Claude Code. Giữ khớp code thật qua `/sync-docs`.
> Chi tiết: `.claude/docs/{structure,features,callflows}.md`.

## Tổng quan

Hệ thống điều khiển nhà thông minh đa hãng: **backend FastAPI (Python 3.13)** làm gateway điều khiển thiết bị qua các connector (Tuya / VeSync / Rojeco), **frontend Flutter** (Android chính) với dashboard, trợ lý giọng nói (AI), và shortcut ra màn hình chính.

- Backend: `backend/app/` — chạy `uvicorn app.main:app` (deploy Render). DB: **SQLite** local (`backend/smarthome.db`, mặc định khi không đặt `DATABASE_URL`) hoặc **Supabase Postgres** (multi-user, xem `backend/docs/SUPABASE_SETUP.md`).
- Frontend: `frontend/lib/` — Flutter + Riverpod-less (dùng `StatefulWidget`/`http` trực tiếp). Android native shortcut qua MethodChannel.
- ✅ **Multi-user (Supabase Auth) — code hoàn chỉnh cả backend lẫn frontend.** Backend: auth JWT + scope `user_id` + liên kết tài khoản VeSync/Tuya + panel admin (test `test_multiuser_scope.py`, 37/37 pass). Frontend: `login_screen.dart` + `AuthGate` + gửi Bearer token + màn "Thêm thiết bị" (`add_device_screen.dart`) + màn Quản trị (`admin_screen.dart`) — `dart analyze` sạch, `flutter build apk --debug` OK. **Cần thiết lập Supabase 1 lần để chạy thật** (xem `backend/docs/SUPABASE_SETUP.md` + mục "Lưu ý an toàn / kỹ thuật").

## Key Features Registry

| Feature | Status | Vị trí chính |
|---|---|---|
| Đa người dùng (Supabase Auth, multi-tenant) | ✅ (cần cấu hình Supabase) | `core/auth.py`, `core/crypto.py`, `models/vendor_account.py`, `services/connector_factory.py`, `backend/docs/supabase_schema.sql`, `frontend/lib/core/auth_service.dart`, `frontend/lib/core/vendor_api.dart`, `frontend/lib/screens/{login,add_device,admin}_screen.dart` |
| Khám phá & liên kết thiết bị (VeSync tự động, Tuya QR bán tự động) | ✅ | `main.py` `/api/vendor/*`, `/api/devices/import`, `services/connector_factory.py`, `frontend/lib/screens/add_device_screen.dart` |
| Trang quản trị (user + thiết bị + gán Tuya) | ✅ | `main.py` `/api/admin/*`, `frontend/lib/screens/admin_screen.dart` |
| Quản lý thiết bị (CRUD) | ✅ | `main.py` `/api/devices`, `models/device.py` |
| Điều khiển bật/tắt & mode | ✅ | `main.py` `/api/test-control/...`, connectors |
| Lấy trạng thái thật thiết bị | ✅ | `main.py` `/api/devices/{brand}/{id}/status` |
| Trợ lý giọng nói (AI + local parse) | ✅ | `main.py` `/api/ai/parse`, `services/ai_parser.py`, `services/local_parser.py`, `screens/ai_assistant_tab.dart` |
| Giọng nói TẠO lịch hẹn (NL → schedule) | ✅ | `services/vn_time_parser.py` (parse giờ tiếng Việt), `local_parser.py` (intent schedule), `main.py` `_create_schedule_from_intent` |
| Dashboard điều khiển | ✅ | `screens/dashboard_tab.dart` |
| Sắp xếp thứ tự thiết bị (kéo-thả) | ✅ | `screens/dashboard_tab.dart` (`SliverReorderableList`), `core/device_order.dart` (lưu SharedPreferences) |
| Home-screen Shortcut (icon xử lý nhanh) | ✅ | `core/shortcut_service.dart`, `core/shortcut_handler.dart`, `MainActivity.kt`, `res/drawable/ic_*` |
| Home Screen Widget (trạng thái sống + điều khiển nền) | ✅ | `core/widget_service.dart`, `SmartHomeWidgetProvider.kt`, `res/layout/smart_home_widget.xml`, package `home_widget` |
| Hẹn giờ thiết bị (đơn + KHOẢNG start→end, qua đêm, one-shot) | ✅ | `services/scheduler.py`, `models/schedule.py`, `main.py` `/api/schedules`, `screens/schedule_tab.dart`, `core/schedule_api.dart` |
| Automation engine | 📋 (đóng băng) | `services/automation_engine.py` (comment trong `main.py`) |

## API Endpoints Summary (`backend/app/main.py`)

Trừ khi ghi chú khác, mỗi endpoint đều `Depends(get_current_user)` (Bearer JWT Supabase, hoặc user giả nếu `AUTH_DISABLED=1`) và **lọc dữ liệu theo `user_id`** của token.

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/devices` | Liệt kê thiết bị **của user hiện tại** (`user_id` filter) |
| POST | `/api/devices` | Thêm thiết bị (query: id, name, brand) — gắn `user_id`; id đã thuộc user khác → lỗi |
| DELETE | `/api/devices/{device_id}` | Xóa thiết bị (lọc theo `user_id`) |
| GET | `/api/test-control/{brand}/{device_id}?action=on\|off` | Bật/tắt — kiểm tra sở hữu (`_get_owned_device`) rồi lấy connector qua `connector_factory.get_user_connector` |
| GET | `/api/test-control/{brand}/{device_id}/mode?mode=...` | Đổi chế độ (open/close/stop/low/high...) — cùng luồng sở hữu + connector theo user |
| GET | `/api/devices/{brand}/{device_id}/status` (opt `?fresh=1`) | **Trạng thái sống** → `{data:{status:ON\|OFF\|offline, door_state, position,...}}`. Cache ~3s key theo `(user_id, brand, device_id)`; `fresh=1` bỏ qua cache. |
| POST | `/api/ai/parse` | Parse + thực thi lệnh NL (body `{text}`), chỉ trên thiết bị của user. Câu CÓ GIỜ ("hẹn 16h30...") → TẠO LỊCH thay vì thi hành ngay |
| GET | `/api/schedules` | Liệt kê lịch hẹn giờ **của user hiện tại** |
| POST | `/api/schedules` | Tạo lịch (body JSON: name, brand, device_id, action_type, action_value, time, days, enabled + lịch khoảng: end_time, end_action_type, end_action_value, one_shot) — 404 nếu `device_id` không thuộc user |
| PATCH | `/api/schedules/{id}` | Sửa lịch / bật-tắt `enabled` (lọc theo `user_id`; đổi giờ/bật lại → reset `last_fired_date`/`last_end_fired_date`; `end_time: null` tường minh → xóa khoảng) |
| DELETE | `/api/schedules/{id}` | Xóa lịch (lọc theo `user_id`) |
| POST | `/api/schedules/{id}/run` (opt `?part=end`) | Chạy NGAY hành động của lịch (test, lọc theo `user_id`, không đổi fired-date); `?part=end` chạy hành động kết thúc |
| GET | `/api/me` | Thông tin user hiện tại: `{user_id, email, is_admin}` (dùng để hiện menu Quản trị phía app) |
| GET | `/api/vendor/accounts` | Liệt kê tài khoản nhà cung cấp đã liên kết của user (`vesync`/`tuya`, trạng thái, có `tuya_uid` hay chưa) |
| POST | `/api/vendor/vesync/connect` | Đăng nhập thử VeSync (body `{email,password}`) → trả danh sách thiết bị để chọn import; lưu credential đã mã hóa vào `vendor_accounts`, invalidate cache connector cũ |
| POST | `/api/devices/import` | Import hàng loạt thiết bị đã chọn (body `{devices:[{id,name,brand,category}]}`) cho user hiện tại; bỏ qua id đã tồn tại |
| GET | `/api/vendor/tuya/link-info` | Hướng dẫn (text tĩnh) liên kết tài khoản Smart Life/Tuya qua QR — vì Tuya không còn API đăng nhập email/mật khẩu |
| POST | `/api/vendor/tuya/discover` | Liệt kê thiết bị Tuya của user — cần đã có `tuya_uid` (do admin gán qua `/api/admin/vendor/tuya/assign`) |
| GET | `/api/admin/users` | **[admin]** Danh sách user + số thiết bị (Postgres: kèm email/tên/role từ `public.profiles`; SQLite: chỉ `user_id`+đếm) |
| GET | `/api/admin/users/{user_id}/devices` | **[admin]** Thiết bị của 1 user bất kỳ |
| POST | `/api/admin/devices/import` | **[admin]** Import thiết bị hộ 1 user (`user_id` chỉ định trong body) |
| GET | `/api/admin/tuya/linked` | **[admin]** Liệt kê tài khoản Smart Life đã liên kết vào project Tuya (`TUYA_APP_SCHEMA`) kèm thiết bị mỗi account |
| POST | `/api/admin/vendor/tuya/assign` | **[admin]** Gán 1 `tuya_uid` đã liên kết cho 1 user (body `{user_id, tuya_uid}`) |
| WS | `/ws` | WebSocket (hiện chỉ echo) |
| GET/HEAD | `/`, `/health` | Health check (UptimeRobot ping giữ server thức), không cần auth |

`[admin]` = `Depends(require_admin)` — 403 nếu email không nằm trong `ADMIN_EMAILS`.

## Database Models (`backend/app/models/`)

- **DeviceModel** (`devices`, `device.py`): `id` (PK, vd `den_phong_khach` — vendor device id), `user_id` (chủ sở hữu, `auth.users.id`), `name`, `brand` (`tuya`\|`vesync`\|`rojeco`), `category` (tùy chọn, chưa dùng nhiều — loại thiết bị vẫn suy từ TÊN phía client qua `core/device_type.dart`, nơi duy nhất), `is_active`, `sort_order`, `created_at`.
- **ScheduleModel** (`schedules`, `schedule.py`): `id` (PK int), `user_id` (chủ sở hữu), `name`, `brand`, `device_id`, `action_type` (`on`\|`off`\|`mode`), `action_value` (mode value, null với on/off), `time` (`"HH:MM"` giờ **Asia/Ho_Chi_Minh**), `days` (CSV weekday Python `0`=Thứ2…`6`=CN, rỗng = mỗi ngày), `enabled`, `last_fired_date` (`"YYYY-MM-DD"` chống kích hoạt trùng trong ngày). **Lịch KHOẢNG**: `end_time` (NULL = lịch đơn; `end_time < time` = QUA ĐÊM, end kích hoạt hôm sau), `end_action_type`, `end_action_value`, `last_end_fired_date`, `one_shot` (chạy 1 lần → tự `enabled=False` sau hành động cuối).
- **VendorAccountModel** (`vendor_accounts`, `vendor_account.py`): `id` (PK int), `user_id`, `brand` (`vesync`\|`tuya`), `credentials_encrypted` (Fernet token — VeSync email/password), `tuya_uid` (uid Smart Life đã liên kết project — Tuya), `label`, `status` (`connected`\|`error`), `created_at`. 1 user tối đa 1 account/brand (unique `user_id+brand` ở Postgres; SQLite không ràng buộc cứng, upsert ở tầng app qua `_upsert_vendor_account`). Ghi qua `POST /api/vendor/vesync/connect` (user tự nhập) hoặc `POST /api/admin/vendor/tuya/assign` (admin gán `tuya_uid` sau khi user liên kết QR).
- Cột mới thêm vào bảng SQLite cũ qua `run_startup_migrations` (`core/database.py`, ALTER TABLE idempotent — create_all không alter bảng cũ; hàm này **chỉ chạy khi dùng SQLite**, Postgres/Supabase quản lý schema qua `backend/docs/supabase_schema.sql`).

## Connectors (`backend/app/services/`)

| Brand | Thiết bị | File | Ghi chú |
|---|---|---|---|
| tuya | Cửa cuốn/rèm | `tuya_connector.py` | state: `door_state`/`position` suy từ DP THẬT trên cloud — ưu tiên vị trí thật (`_POSITION_DPS`) → tình trạng thật (`_WORK_STATE_DPS`) → fallback DP `control` (lệnh cuối). Danh sách tên DP là ứng viên, bổ sung nếu log `[Tuya Door] ⚠️` báo tên lạ. `list_app_users(schema)`/`list_user_devices(uid)` phục vụ `GET /api/admin/tuya/linked` + `POST /api/vendor/tuya/discover`. |
| vesync | Máy lọc khí | `vesync_connector.py` | state: `mode`, `speed`. `list_devices()` phục vụ `POST /api/vendor/vesync/connect` (chọn thiết bị để import). `connect()` sửa lỗi truyền `time_zone` — pyvesync 3.x tham số vị trí thứ 3 là `country_code`, phải truyền qua keyword. |
| rojeco | Máy cho ăn thú cưng | `rojeco_connector.py` | ⚠️ `get_device_state` là **stub** luôn trả `"ON"` |

Tất cả kế thừa `base_connector.py`. **Phân giải theo user** qua `connector_factory.get_user_connector(db, user_id, brand)` (thay cho gọi thẳng `device_manager` ở code điều khiển):
- **Tuya/Rojeco**: dùng chung 1 project (token chung) → connector **singleton toàn app**, đăng ký qua `connector_manager.py` lúc lifespan startup (bọc try/except — 1 hãng lỗi không sập app).
- **VeSync**: đăng nhập theo TỪNG tài khoản user → connector tạo lười theo user (KHÔNG khởi tạo ở lifespan nữa), credential lấy từ `vendor_accounts.credentials_encrypted` (giải mã bằng `core/crypto.py`), cache theo `user_id` trong `_vesync_cache` (module-level dict, mất khi restart) để khỏi login lại mỗi lệnh. `connector_factory.invalidate_user(user_id)` gọi khi user kết nối lại VeSync (`/api/vendor/vesync/connect`) để buộc dùng credential mới.

## File quan trọng nhất

- `backend/app/main.py` — toàn bộ endpoint + luồng AI parse + lifespan (connectors + scheduler task).
- `backend/app/core/database.py` — chọn engine SQLite (local) hoặc Postgres/Supabase (`DATABASE_URL`), `init_db()` (create_all + migration SQLite), `run_startup_migrations()`.
- `backend/app/core/auth.py` — verify JWT Supabase (`get_current_user`), `require_admin`; `AUTH_DISABLED=1` để bỏ qua khi dev local.
- `backend/app/core/crypto.py` — mã hóa/giải mã credential nhà cung cấp (Fernet, khóa `FERNET_KEY`).
- `backend/app/services/connector_factory.py` — phân giải connector THEO USER (`get_user_connector`); Tuya/Rojeco singleton, VeSync per-user cache; `discover_vesync` dùng bởi `/api/vendor/vesync/connect`.
- `backend/app/models/vendor_account.py` — `VendorAccountModel` (tài khoản nhà cung cấp đã liên kết).
- `backend/docs/supabase_schema.sql` + `backend/docs/SUPABASE_SETUP.md` — schema Postgres (profiles/vendor_accounts/devices/schedules + RLS) và hướng dẫn thiết lập Supabase.
- `backend/app/services/scheduler.py` — vòng lặp Hẹn giờ (tick 30s, grace 120s, TZ Asia/Ho_Chi_Minh; bắn start + end độc lập, qua đêm dịch ngày +1, one-shot tự tắt).
- `backend/app/services/vn_time_parser.py` — parse giờ tiếng Việt ("16 giờ 30", "4 giờ chiều", "từ X đến Y", "mai", "mỗi ngày") cho lệnh hẹn giờ bằng giọng nói; `resolve_target_days` quy đổi sang days/one_shot.
- `frontend/lib/core/config.dart` — nơi DUY NHẤT khai báo baseUrl/wsUrl/timeout + `supabaseUrl`/`supabaseAnonKey` (override qua `--dart-define`).
- `frontend/lib/core/auth_service.dart` — bọc Supabase Auth (`init`/`signIn`/`signUp`/`signOut`) + `authHeaders()` gắn Bearer token cho mọi request tới backend; `fetchMe()` hỏi `/api/me`.
- `frontend/lib/screens/login_screen.dart` — màn đăng nhập/đăng ký email+mật khẩu; `main.dart` có `AuthGate` chuyển màn theo `AuthService.isLoggedIn`.
- `frontend/lib/core/shortcut_handler.dart` — điều phối hành vi shortcut + `ShortcutIcons` (map trạng thái → tên drawable).
- `frontend/lib/core/shortcut_service.dart` — MethodChannel `smarthome/shortcuts` ↔ native, quick_actions iOS.
- `frontend/android/.../MainActivity.kt` — build/pin/update shortcut, `resolveIcon()`.
- `frontend/lib/screens/dashboard_tab.dart` — UI thiết bị + nút tạo shortcut + đẩy trạng thái lên widget + tên user động + nút "Thêm thiết bị" (mở `add_device_screen.dart`) + menu tài khoản (đăng xuất / Quản trị nếu admin, mở `admin_screen.dart`).
- `frontend/lib/screens/add_device_screen.dart` — luồng khám phá & chọn thiết bị: VeSync (nhập email/pass → liệt kê → tick chọn/"Chọn hết" → import) và Tuya (hướng dẫn QR → `discover` → chọn → import). Gọi qua `core/vendor_api.dart`.
- `frontend/lib/screens/admin_screen.dart` — màn Quản trị (chỉ admin): tab Người dùng (xem thiết bị từng user) + tab Tuya liên kết (gán `tuya_uid` cho user, import thiết bị hộ).
- `frontend/lib/core/vendor_api.dart` — client cho các endpoint `/api/vendor/*`, `/api/devices/import`, `/api/admin/*`.
- `frontend/lib/screens/schedule_tab.dart` — tab Hẹn giờ (list + form bottom-sheet).
- `frontend/lib/core/widget_service.dart` — đẩy trạng thái lên App Widget + callback nền xử lý nút widget.
- `frontend/android/.../SmartHomeWidgetProvider.kt` — AppWidgetProvider render 3 khe thiết bị.

## Lưu ý an toàn / kỹ thuật

- **Credential ở biến môi trường**: `backend/.env` (gitignore, mẫu ở `backend/.env.example`) — `TUYA_ACCESS_ID/KEY/API_ENDPOINT` (+ `TUYA_APP_SCHEMA` bắt buộc cho `GET /api/admin/tuya/linked`), `OPENROUTER_API_KEY`, và bộ multi-user `DATABASE_URL`/`SUPABASE_JWT_SECRET`/`FERNET_KEY`/`ADMIN_EMAILS`/`AUTH_DISABLED`. Trên Render set trong Dashboard > Environment. Thiếu `OPENROUTER_API_KEY` app vẫn boot (AI client khởi tạo lười, local parser vẫn chạy). ⚠️ `VESYNC_EMAIL/PASSWORD` KHÔNG còn dùng — mỗi user tự nhập credential VeSync qua `POST /api/vendor/vesync/connect`, lưu mã hóa ở `vendor_accounts`.
- **Đa người dùng (Supabase Auth) — ✅ backend + frontend hoàn chỉnh (cần cấu hình Supabase để chạy thật):**
  - Backend verify Bearer JWT qua `core/auth.get_current_user` (HS256, `SUPABASE_JWT_SECRET`), MỌI endpoint (kể cả `DELETE`/`run` lịch) đã lọc theo `user.user_id`. `AUTH_DISABLED=1` trả user giả cố định (`_DEV_USER_ID`) để test local không cần Supabase — TUYỆT ĐỐI không bật trên production. Kiểm chứng bằng `backend/tests/test_multiuser_scope.py` (401 khi thiếu token, cách ly dữ liệu 2 user, 404 khi đụng thiết bị người khác) — 37/37 test pass.
  - DB chọn qua `DATABASE_URL`: rỗng → SQLite local (như cũ); có giá trị → Postgres/Supabase (schema quản lý riêng bằng `backend/docs/supabase_schema.sql`, có RLS làm hàng phòng thủ thứ hai dù backend đã tự scope theo `user_id`).
  - Credential VeSync mã hóa bằng Fernet (`core/crypto.py`, khóa `FERNET_KEY`) trước khi lưu `vendor_accounts.credentials_encrypted`.
  - Liên kết tài khoản: VeSync tự phục vụ (`/api/vendor/vesync/connect` → chọn thiết bị → `/api/devices/import`); Tuya cần **admin hỗ trợ 1 lần** (user quét QR link app account trong Smart Life → admin xem `/api/admin/tuya/linked` → gán `tuya_uid` qua `/api/admin/vendor/tuya/assign` → user tự `/api/vendor/tuya/discover` để import).
  - Frontend ĐÃ tích hợp Supabase Auth: `AuthGate` (`main.dart`) chuyển `LoginScreen`↔`MainScreen` theo `AuthService.isLoggedIn`; mọi request qua `DeviceApi`/`ScheduleApi`/`dashboard_tab` đã gắn `AuthService.authHeaders()`; `DeviceOrder` (SharedPreferences) khóa theo `user.id` để nhiều tài khoản trên cùng máy không đè thứ tự của nhau.
  - UI khám phá đã hoàn tất: `add_device_screen.dart` (VeSync + Tuya) và `admin_screen.dart` (`/api/admin/*`) đã tạo; `dart analyze` **sạch (No issues)** và `flutter build apk --debug` **build OK**.
  - ⚠️ **Để chạy thật cần thiết lập Supabase 1 lần**: tạo project + chạy `backend/docs/supabase_schema.sql` + điền `DATABASE_URL`/`SUPABASE_JWT_SECRET`/`FERNET_KEY`/`ADMIN_EMAILS` (backend) và `--dart-define=SUPABASE_URL=... --dart-define=SUPABASE_ANON_KEY=...` (frontend). Xem `backend/docs/SUPABASE_SETUP.md`. Chưa cấu hình thì app vẫn build nhưng đăng nhập sẽ lỗi (chưa có project Supabase thật).
- **Hẹn giờ (scheduler)**: task asyncio khởi động trong lifespan, tick 30s; mốc kích hoạt khi `now` (giờ VN) vào cửa sổ `[giờ hẹn, +120s)` và fired-date != hôm nay (đánh dấu TRƯỚC khi gửi lệnh — lệnh lỗi không bắn lặp). **Lịch KHOẢNG**: start và end bắn ĐỘC LẬP (restart giữa khoảng vẫn trả thiết bị về trạng thái "sau"); qua đêm (`end < time`) → ngày check end dịch +1 (`_end_days`). **One-shot**: lịch đơn tắt sau start, lịch khoảng tắt sau end; lỡ trọn cửa sổ (server ngủ) → tự tắt + log, tránh bắn nhầm tuần sau. Server được **UptimeRobot ping /health** giữ thức. ⚠️ Ổ đĩa Render free là ephemeral — lịch trong SQLite **mất khi redeploy** (cân nhắc DB ngoài nếu cần bền). Cần `tzdata` trong requirements (zoneinfo trên Render/Windows).
- **Giọng nói tạo lịch**: local parser gọi `extract_schedule_times` TRƯỚC — câu có giờ ⇒ CHỈ trả `{"intent":"schedule",...}` (tuyệt đối không thi hành ngay; "hẹn 16h30 bật quạt" không được bật quạt luôn); không rõ thiết bị → `[]` cho AI fallback (prompt `ai_parser.py` có few-shot schedule cùng shape). `main.py._create_schedule_from_intent` map verb → cột lịch, `resolve_target_days` ghim thứ + one_shot (giờ đã qua → tự hiểu ngày mai), tạo row qua `_create_schedule_row` (dùng chung POST endpoint), trả bubble "Đã hẹn 16:30 • Chế độ 3". Khoảng không nói hành động kết thúc → mặc định Tắt (cửa mở → đóng; cửa đóng/dừng KHÔNG đoán — an toàn, thành lịch đơn). Test: `backend/tests/` (pytest).
- Pinned shortcut Android là ảnh tĩnh: trạng thái phản ánh qua **icon**, không có badge/text sống. Icon hội tụ về trạng thái THẬT **khi app đang chạy** — `dashboard_tab._syncShortcutIcon` đẩy icon mỗi vòng poll 6s (bắt kịp cả khi điều khiển bằng remote vật lý/app khác), và `_reconcileDoorIcon` chỉnh icon cửa theo trạng thái thật sau khi bấm shortcut. App đóng hoàn toàn thì icon giữ nguyên tới lần app mở kế. Trạng thái sống đầy đủ hơn có ở Home Screen Widget.
- Tên drawable icon shortcut phải khớp CHÍNH XÁC với `ShortcutIcons` (`shortcut_handler.dart`), nếu thiếu → native fallback về `launcher_icon` (logo app).
- **Điều khiển & trạng thái (perf/UX):** endpoint control trả `{status:"error"}` khi thiết bị không nhận lệnh (không còn luôn "success"); connector Tuya/Rojeco dùng `asyncio.to_thread` để không block event loop; status có cache ~3s (`_status_cache`, `?fresh=1` để bỏ cache; **mọi đường điều khiển** — endpoint control, AI executor, scheduler — đều invalidate cache sau lệnh). Card máy lọc/cửa tự poll 6s **chỉ khi tab Home hiển thị + app foreground** (`pollingEnabled`, `WidgetsBindingObserver`); nút có `_sending` chặn double-tap + tô sáng lạc quan `_pendingMode`. ⚠️ Tô sáng lạc quan **reconcile theo giá trị**: chỉ xóa `_pendingMode` khi trạng thái thật khớp mode vừa bấm (hoặc timeout ~10s) — nếu clear mù khi cloud chưa propagate thì highlight sẽ nhảy về mode cũ. Nút cửa luôn bấm được (bỏ khóa), chỉ tô sáng nút đang hoạt động. Card báo trạng thái thật về parent (`onStatusChanged`) để header đếm "Đang bật" đúng.
- **AI executor** nhận cả `action` = `on|off` (AI) lẫn `turn_on|turn_off` (local parser) — sửa lỗi lệnh local "bật/tắt" rơi vào khoảng trống.
- **WebSocket**: `wss://vuhp-smarthome.onrender.com/ws` (`AppConfig.wsUrl`), tự connect khi vào tab AI, chỉ báo "Live" sau khi `channel.ready` (bắt tay xong), giữ tối đa 200 message.
- Server Render free-tier có thể **ngủ** (nếu UptimeRobot gián đoạn) → app `_bootstrap()` ping `/health` (timeout 35s) và hiện "Đang đánh thức máy chủ..." trước khi tải.

## Lệnh hay dùng

```bash
# Backend
cd backend && uvicorn app.main:app --reload
# Frontend
cd frontend && flutter pub get && flutter run
cd frontend && dart analyze
cd frontend && flutter build apk --debug
```
