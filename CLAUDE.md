# CLAUDE.md — SmartHomeProject

> Tài liệu điều hướng cho Claude Code. Giữ khớp code thật qua `/sync-docs`.
> Chi tiết: `.claude/docs/{structure,features,callflows}.md`.

## Tổng quan

Hệ thống điều khiển nhà thông minh đa hãng: **backend FastAPI (Python 3.13)** làm gateway điều khiển thiết bị qua các connector (Tuya / VeSync / Rojeco), **frontend Flutter** (Android chính) với dashboard, trợ lý giọng nói (AI), và shortcut ra màn hình chính.

- Backend: `backend/app/` — chạy `uvicorn app.main:app` (deploy Render). DB SQLite `backend/smarthome.db`.
- Frontend: `frontend/lib/` — Flutter + Riverpod-less (dùng `StatefulWidget`/`http` trực tiếp). Android native shortcut qua MethodChannel.

## Key Features Registry

| Feature | Status | Vị trí chính |
|---|---|---|
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
| Lưu dữ liệu bền (Postgres/Supabase) | 🚧 project Supabase đã tạo bảng (region Tokyo), chờ merge `main` + đặt `DATABASE_URL` trên Render | `core/database.py`, `docs/supabase_schema.sql`, `docs/SUPABASE_SETUP.md` |
| Đăng nhập (Supabase Auth) + AuthGate 5 trạng thái | 🚧 code xong, chưa bật production | `core/auth_service.dart`, `screens/{auth_gate,login_screen,pending_screen}.dart`, `core/auth.py` |
| Khu vực + thành viên + phân quyền theo khu | 🚧 code xong, chưa bật production | `core/household.py` (nơi DUY NHẤT quyết định quyền), `core/auth.py`, `models/{member,zone}.py`, `main.py` `/api/{me,zones,members}`, `screens/admin_screen.dart`, `core/household_api.dart` |
| Kịch bản (1 nút nhiều thiết bị, chạy bằng giọng nói) | ✅ | `models/scene.py`, `main.py` `/api/scenes`, `core/scene_api.dart`, `screens/scene_editor_screen.dart` |
| Khu dùng chung cả nhà + dashboard lọc theo khu | ✅ | `zones.is_shared`, `household._visible_zone_ids`, `core/zone_groups.dart` |
| Giao diện sáng/tối (Theo hệ thống/Sáng/Tối) | ✅ | `theme/app_colors.dart` (`AppPalette`, `context.palette`), `core/theme_controller.dart` |
| Hồ sơ cá nhân (tên, màu avatar, giao diện, đọc phản hồi) | ✅ | `PATCH /api/me`, `screens/profile_screen.dart`, `core/avatar.dart` |
| Trợ lý đọc phản hồi (TTS vi-VN) | ✅ | `core/voice_feedback.dart` (flutter_tts) |
| Quên mật khẩu (mã OTP qua email) + đổi mật khẩu | ✅ | `screens/forgot_password_screen.dart`, `screens/password_field.dart`, `AuthService.sendPasswordResetCode/resetPasswordWithCode/changePassword`, Hồ sơ → Tài khoản |
| Hướng dẫn sử dụng trong app + giới thiệu lần đầu | ✅ | `screens/help_screen.dart` (`helpTopics` — nơi DUY NHẤT chứa nội dung), `screens/onboarding_screen.dart` |
| Automation engine | 📋 (đóng băng) | `services/automation_engine.py` (comment trong `main.py`) |

## API Endpoints Summary (`backend/app/main.py`)

| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/auth/app-token` | Cấp **token dài hạn** cho app lưu SharedPreferences — đường sống của Home Widget/shortcut ở isolate nền. Thu hồi = đổi `APP_TOKEN_SECRET`. Token cấp lúc xác thực TẮT (`sub`=`DEV_USER_ID`) bị từ chối khi đã bật |
| PATCH | `/api/me` | Sửa hồ sơ của CHÍNH MÌNH (`{display_name?, avatar_color?}` — tên 1-40 ký tự, màu `#RRGGBB`/null). Không có vai/trạng thái. Pending sửa được, blocked thì không |
| GET/POST | `/api/scenes`, `/api/scenes/{id}` (PATCH/DELETE) | Kịch bản. Đọc: mọi thành viên active. Tạo/sửa/xóa: owner/adult. Hành động được CHUẨN HÓA theo loại lúc lưu (sai loại → 400) |
| POST | `/api/scenes/{id}/run` | Chạy kịch bản TUẦN TỰ; hành động trên thiết bị ngoài khu của người chạy → bỏ qua (`skipped`) |
| GET | `/api/me` | **Tôi là ai**: vai, trạng thái, khu được cấp. KHÔNG chặn `pending` — app cần đọc để biết hiện màn hình chờ duyệt hay màn hình chính |
| GET | `/api/devices` | Liệt kê thiết bị **đã lọc theo khu được cấp**; trả kèm `zone_id`/`zone_name`/`category` |
| POST | `/api/devices` | Thêm thiết bị (query: id, name, brand, opt zone_id, opt category). **Chỉ chủ nhà.** Idempotent — id trùng = "đã có trong nhà", không phải lỗi |
| PATCH | `/api/devices/{device_id}` | Đổi tên / **gán khu** / đặt loại (body `{name?, zone_id?, category?}`). Chỉ chủ nhà |
| DELETE | `/api/devices/{device_id}` | Xóa thiết bị **+ mọi lịch của nó** (lịch mồ côi sẽ bắn vào thiết bị không tồn tại mãi mãi). Chỉ chủ nhà |
| GET/POST | `/api/zones`, `/api/zones/{id}` (PATCH/DELETE) | Khu vực (kèm `is_shared` = dùng chung cả nhà). Đọc: ai cũng được (chỉ thấy khu của mình). Sửa: chỉ chủ nhà. Xóa khu → thiết bị về "hộp thư đến", KHÔNG bị xóa theo |
| GET | `/api/members` | Danh sách thành viên + khu được cấp. Chỉ chủ nhà |
| PATCH | `/api/members/{user_id}` | Duyệt / đổi vai / cấp khu (`{role?, status?, display_name?, zone_ids?}` — `zone_ids` thay CẢ BỘ). Chặn tự hạ vai, tự chặn mình, hạ vai owner cuối cùng |
| GET | `/api/test-control/{brand}/{device_id}?action=on\|off` | Bật/tắt. `action` khác on/off → **400** (trước đây = tắt = đóng cửa). Hãng lấy từ DB, không tin URL |
| GET | `/api/test-control/{brand}/{device_id}/mode?mode=...` | Đổi chế độ (open/close/stop/low/high...) |
| GET | `/api/devices/{brand}/{device_id}/status` (opt `?fresh=1`) | **Trạng thái sống** → `{data:{status:ON\|OFF\|offline, door_state, position,...}}`. Có cache ~3s; `fresh=1` bỏ qua cache (dùng sau lệnh điều khiển). |
| POST | `/api/ai/parse` | Parse + thực thi lệnh NL (body `{text}`). Câu CÓ GIỜ ("hẹn 16h30...") → TẠO LỊCH thay vì thi hành ngay. Parser chỉ nhìn thấy thiết bị trong khu được cấp ⇒ scoping tự động |
| GET | `/api/schedules` | Liệt kê lịch hẹn giờ (lọc theo THIẾT BỊ thấy được, không theo người tạo — lịch là của cả nhà) |
| POST | `/api/schedules` | Tạo lịch (body JSON: name, brand, device_id, action_type, action_value, time, days, enabled + lịch khoảng: end_time, end_action_type, end_action_value, one_shot) |
| PATCH | `/api/schedules/{id}` | Sửa lịch / bật-tắt `enabled` (đổi giờ/bật lại → reset `last_fired_date`/`last_end_fired_date`; `end_time: null` tường minh → xóa khoảng) |
| DELETE | `/api/schedules/{id}` | Xóa lịch |
| POST | `/api/schedules/{id}/run` (opt `?part=end`) | Chạy NGAY hành động của lịch (test), không đổi fired-date; `part=end` chạy hành động kết thúc |
| WS | `/ws` | WebSocket (hiện chỉ echo) |
| GET/HEAD | `/`, `/health` | Health check (UptimeRobot ping giữ server thức). `/health` trả `{status:"online", db:true\|false}` — **luôn 200**; `db:false` = app sống nhưng DB chưa khởi tạo được (boot degraded) |

## Database Models (`backend/app/models/`)

- **DeviceModel** (`devices`, `device.py`): `id` (PK = id THẬT của hãng), `name`, `brand` (`tuya`\|`vesync`\|`rojeco`), `is_active`, `zone_id` (FK `zones.id`, `ON DELETE SET NULL`, **NULL = "hộp thư đến"** chỉ owner/adult thấy), `category` (NULL = client tự suy từ tên).
  - ⚠️ **Không đổi PK sang surrogate id**: `schedules.device_id`, `local_parser`, `DeviceOrder`, **shortcut đã pin** và **Home Widget** đều tham chiếu id này — đổi là mồ côi hết shortcut/widget trên điện thoại cả nhà, không báo lỗi.
  - `category` ∈ `DEVICE_CATEGORIES` (`purifier`\|`curtain`\|`feeder`\|`switch`, `models/device.py`) — PATCH ngoài tập này → 400; chủ nhà đặt ở màn quản trị (chạm vào dòng thiết bị). Client phân loại qua `core/device_type.dart` (nơi duy nhất): **category thắng**, NULL/lạ → suy từ TÊN như cũ. Backend có bản tương ứng `device_kind()` (cùng file `models/device.py`: category > tên > hãng) cho parser giọng nói. ⚠️ Từ khóa công tắc (`bơm`/`tăng áp`/`công tắc`) kiểm TRƯỚC máy cho ăn vì "t**ăn**g áp" chứa "ăn". Thêm loại mới phải sửa CẢ `DEVICE_CATEGORIES` lẫn `deviceCategories` (Dart). Seed + `supabase_schema.sql` điền sẵn category cho 3 thiết bị gốc (SQL chỉ backfill hàng còn NULL).
- **MemberModel** (`members`, `member.py`): `user_id` (PK, = `auth.users.id` của Supabase dạng text), `email`, `display_name`, `role` (`owner`\|`adult`\|`kid`\|`guest`), `status` (`pending`\|`active`\|`blocked`). Người lạ đăng nhập lần đầu → `guest`/`pending`.
- **ZoneModel** (`zones`, `zone.py`): `id`, `name`, `sort_order`. **MemberZoneAccessModel** (`member_zone_access`): `(user_id, zone_id)` PK ghép — grant CHỈ cho `kid`/`guest`; `owner`/`adult` thấy mọi khu theo luật vai nên không có hàng nào ở đây.
- **MemberModel.avatar_color** (đợt 2): `#RRGGBB` tự chọn; NULL = app suy màu ổn định từ user_id. **ZoneModel.is_shared** (đợt 2, `server_default` false vì `seed_defaults` chèn bằng SQL thô): kid/guest thấy + điều khiển thiết bị khu dùng chung không cần grant.
- **SceneModel** (`scenes`, `scene.py`): `id`, `name`, `icon` (tên icon phía app), `sort_order`, `actions` (JSON text `[{device_id, action_type, action_value}]` đã chuẩn hóa), `created_by` (audit). Không gắn khu — kịch bản của cả nhà.
- **ScheduleModel** (`schedules`, `schedule.py`): `id` (PK int), `name`, `brand`, `device_id`, `action_type` (`on`\|`off`\|`mode`), `action_value` (mode value, null với on/off), `time` (`"HH:MM"` giờ **Asia/Ho_Chi_Minh**), `days` (CSV weekday Python `0`=Thứ2…`6`=CN, rỗng = mỗi ngày), `enabled`, `last_fired_date` (`"YYYY-MM-DD"` chống kích hoạt trùng trong ngày). **Lịch KHOẢNG**: `end_time` (NULL = lịch đơn; `end_time < time` = QUA ĐÊM, end kích hoạt hôm sau), `end_action_type`, `end_action_value`, `last_end_fired_date`, `one_shot` (chạy 1 lần → tự `enabled=False` sau hành động cuối), `created_by` (CHỈ để audit + chặn kid sửa lịch người khác — lịch là của **cả nhà**, không lọc theo cột này). Cột mới thêm qua `run_startup_migrations` (`core/database.py`, ALTER TABLE idempotent — create_all không alter bảng cũ; chạy cho cả SQLite lẫn Postgres, DDL tách riêng vì Boolean SQLite là `INTEGER` còn Postgres là `BOOLEAN`).

- **Nơi lưu DB**: biến `DATABASE_URL` → Postgres (Supabase); không đặt → SQLite `backend/smarthome.db` như cũ. ⚠️ Còn chạy SQLite trên Render thì **lịch hẹn mất mỗi lần redeploy** — ổ đĩa ephemeral, mà `smarthome.db` lại bị track trong git nên container mới ghi đè bằng bản chụp trong repo (bảng `schedules` rỗng). Log lúc boot in rõ đang dùng loại nào. Cách chuyển: `backend/docs/SUPABASE_SETUP.md`.

## Connectors (`backend/app/services/`)

| Brand | Thiết bị | File | Ghi chú |
|---|---|---|---|
| tuya | Cửa cuốn/rèm **+ công tắc** (máy bơm tăng áp) | `tuya_connector.py` | Tự phân loại theo category Tuya (tra `/v1.0/devices/{id}` 1 lần, cache): `_SWITCH_CATEGORIES` (`tdq`, `kg`, `cz`...) → điều khiển DP `switch_1`, state ON/OFF/offline; **không bao giờ** gửi `control` tới công tắc. Cửa: đọc `shadow/properties` (có THỜI ĐIỂM DP) — ưu tiên vị trí thật → tình trạng thật → fallback DP `control` (lệnh cuối): lệnh cũ hơn `_DOOR_TRAVEL_SECONDS`=30s → `open`/`closed`, mới hơn → `opening`/`closing`. ⚠️ Cửa nhà hiện là **'Curtain switch' (`clkg`) chỉ có DP `control`** — không có vị trí thật; bấm công tắc tường Tuya CÓ báo lên cloud, còn remote RF điều khiển thẳng motor thì cloud KHÔNG biết (cần cảm biến cửa). |
| vesync | Máy lọc khí | `vesync_connector.py` | state: `mode`, `speed` |
| rojeco | Máy cho ăn thú cưng (Tuya category `cwwsq`) | `rojeco_connector.py` | state: `status` ON (online, = sẵn sàng) / `offline` từ `online` của device info; `feed_state` (`standby`\|`feeding`\|`done`), `last_feed` (DP `feed_report`). Máy **không** báo mức hạt/pin. Dashboard chỉ đọc khi card hiện + sau lệnh (không poll 6s — tiết kiệm quota Tuya). |

Tất cả kế thừa `base_connector.py`; đăng ký qua `connector_manager.py` (`device_manager`) lúc startup (lifespan, mỗi connector bọc try/except — 1 hãng lỗi không sập app).

## File quan trọng nhất

- `backend/app/main.py` — toàn bộ endpoint + luồng AI parse + lifespan (khởi tạo DB → connectors → scheduler task).
- `backend/app/core/household.py` — **NƠI DUY NHẤT quyết định quyền**: `device_query`/`schedule_query` (lọc theo khu), `require_device_access`/`require_schedule_write`/`require_owner`, `provision_member`. Quyền KHÔNG xuất hiện trong thân endpoint nào.
- `backend/app/core/auth.py` — verify JWT Supabase; cố tình **sạch model + sạch DB**. `auth_disabled()` tự suy từ `SUPABASE_JWT_SECRET`.
- `backend/app/services/device_actions.py` — `normalize_action(device, verb, mode)`: whitelist hành động theo LOẠI (cửa chỉ open/close/stop — KHÔNG on/off; máy cho ăn 1-10 phần; công tắc on/off). **Mọi đường không qua UI** (AI, lịch bằng giọng nói, kịch bản) đi qua đây trước connector.
- `backend/app/services/scheduler.py` — vòng lặp Hẹn giờ (tick 30s, grace 120s, TZ Asia/Ho_Chi_Minh; bắn start + end độc lập, qua đêm dịch ngày +1, one-shot tự tắt).
- `backend/app/services/vn_time_parser.py` — parse giờ tiếng Việt ("16 giờ 30", "4 giờ chiều", "từ X đến Y", "mai", "mỗi ngày") cho lệnh hẹn giờ bằng giọng nói; `resolve_target_days` quy đổi sang days/one_shot.
- `frontend/lib/core/config.dart` — nơi DUY NHẤT khai báo baseUrl/wsUrl/timeout + khóa Supabase (`--dart-define`); `authEnabled` false khi chưa có khóa ⇒ app bỏ qua đăng nhập.
- `frontend/lib/core/auth_service.dart` — `accessToken()` (Supabase → fallback **app-token**), `headers()` ném lỗi rõ thay vì im lặng bỏ header, `handleUnauthorized()`; `HouseholdProfile` + `fetchMe()`.
- `frontend/lib/screens/auth_gate.dart` — 5 trạng thái `loading|signedOut|pending|offline|ready`, quyết định hiện màn nào.
- `frontend/lib/screens/admin_screen.dart` — 2 tab quản trị (Thành viên: pending ghim đầu, đổi vai/trạng thái/tick khu; Khu vực: CRUD + gán thiết bị, pseudo-zone "Chưa phân khu" ghim cuối).
- `frontend/lib/core/household_api.dart` — client `/api/zones`, `/api/members`, `PATCH /api/devices/{id}`; `Zone`/`Member` model.
- `frontend/lib/core/shortcut_handler.dart` — điều phối hành vi shortcut + `ShortcutIcons` (map trạng thái → tên drawable).
- `frontend/lib/core/shortcut_service.dart` — MethodChannel `smarthome/shortcuts` ↔ native, quick_actions iOS.
- `frontend/android/.../MainActivity.kt` — build/pin/update shortcut, `resolveIcon()`.
- `frontend/lib/screens/dashboard_tab.dart` — UI thiết bị + nút tạo shortcut + đẩy trạng thái lên widget.
- `frontend/lib/screens/schedule_tab.dart` — tab Hẹn giờ (list + form bottom-sheet). Danh sách hành động theo loại nằm ở `core/device_type.dart` (`deviceActionOptions`, dùng chung với form kịch bản).
- `frontend/lib/theme/app_colors.dart` — `AppPalette` (ThemeExtension, bản dark = màu gốc, bản light), đọc qua `context.palette` — KHÔNG dùng màu hằng cho nền/chữ (vô hình ở theme kia).
- `frontend/lib/screens/profile_screen.dart` — Hồ sơ & giao diện; `core/voice_feedback.dart` — TTS + `summarize()` kết quả AI.
- `frontend/lib/core/widget_service.dart` — đẩy trạng thái lên App Widget + callback nền xử lý nút widget.
- `frontend/android/.../SmartHomeWidgetProvider.kt` — AppWidgetProvider render 3 khe thiết bị; `onEnabled`/`onUpdate` đăng ký `WidgetRefreshWorker` (WorkManager 15 phút — tối thiểu Android cho phép) bắn `smarthome://refresh` để widget tự lấy trạng thái mới khi app ĐÓNG (`updatePeriodMillis` chỉ vẽ lại dữ liệu cũ, không hỏi backend). Chỉ ĐỌC, không gửi lệnh.

## Lưu ý an toàn / kỹ thuật

- **Credential ở biến môi trường**: `backend/.env` (gitignore, mẫu ở `backend/.env.example`) — `VESYNC_EMAIL/PASSWORD`, `TUYA_ACCESS_ID/KEY/API_ENDPOINT`, `OPENROUTER_API_KEY`, `DATABASE_URL` (tùy chọn — không đặt thì dùng SQLite), `SUPABASE_JWT_SECRET` + `ADMIN_EMAILS` + `APP_TOKEN_SECRET` + `AUTH_DISABLED` (xác thực). Trên Render set trong Dashboard > Environment. Thiếu `OPENROUTER_API_KEY` app vẫn boot (AI client khởi tạo lười, local parser vẫn chạy).
- **Deploy Render / dependency**: có **HAI** file requirements. `backend/requirements.txt` là danh sách THẬT; `requirements.txt` ở thư mục gốc chỉ là **con trỏ** `-r backend/requirements.txt` (pip resolve đường dẫn trong `-r` theo thư mục của file, nên chạy từ repo root vẫn đúng). ⚠️ Trước đây file gốc là một bản SAO CHÉP UTF-16LE và đã lệch phía sau — thêm `PyJWT` vào `backend/requirements.txt` mà không thêm vào file gốc đã làm **sập production** (`ModuleNotFoundError: No module named 'jwt'` lúc import → `Error loading ASGI app`). Dạng con trỏ khiến không thể lệch được nữa. **Không xóa file gốc** trước khi xác nhận Root Directory trong Render Dashboard: service tạo tay trên dashboard KHÔNG đọc `render.yaml`. `render.yaml` ghim `rootDir: backend`, build/start command, `healthCheckPath: /health`, `PYTHON_VERSION=3.13.5`. `psycopg2-binary==2.9.11` (có wheel cả cp313 lẫn cp314 — service tạo tay không đọc `PYTHON_VERSION` của `render.yaml`). Đã bỏ cụm gói `google-*`/`grpcio` không dùng (AI chỉ qua `openai` → OpenRouter).
- **⚠️ `main` từng REVERT Phase 0** (`32ebd11`, vì deploy lỗi trên Render — chưa có log xác định nguyên nhân). Mọi phase sau xây TRÊN Phase 0 ⇒ merge thẳng vào `main` sẽ âm thầm áp lại revert (mất `PyJWT` → sập lúc import). Nhánh `release/prod-ready` đã revert-of-revert + merge Phase 1a→3 nên `main` chỉ cần **fast-forward**. Dev local: Python **3.13** (`.venv`), Flutter SDK ở `D:lutter`.
- **Khởi tạo DB không được làm sập app**: `init_db()` (`core/database.py`) chạy `create_all` → `run_startup_migrations` → `verify_schema` → `enable_rls` → `seed_defaults`, gọi **trong lifespan** (bọc try/except → cờ `db_ready`), KHÔNG gọi ở tầng import. **Thứ tự quan trọng — verify TRƯỚC seed**: ngược lại thì schema lệch làm seed ném `OperationalError` thô của SQLAlchemy, che mất thông báo nói rõ thiếu bảng/cột nào. `enable_rls` bật RLS trên Postgres nhưng **không viết policy** (Supabase grant sẵn cho `anon`/`authenticated`, mà anon key nằm trong APK; bật RLS không policy = deny-all, backend nối bằng role `postgres` nên bỏ qua RLS). `seed_defaults` chỉ chạy khi `devices` rỗng và **giữ nguyên id** — shortcut đã pin và slot Home Widget lưu theo `brand`+`id`. Lý do: exception ở tầng import làm uvicorn chết với `Error loading ASGI app` — không route nào chạy, kể cả `/health`, nên UptimeRobot flatline và không phân biệt được "lỗi DB" với "app chết". Nay lỗi DB → boot degraded, `/health` vẫn 200 với `db:false` và log nói rõ nguyên nhân.
- **Phân quyền (Phase 1b)**: mô hình là **thiết bị thuộc KHU, thành viên được cấp quyền theo KHU** — không phải `devices.user_id` sở hữu phẳng (mô hình đó không chia sẻ được thiết bị, mà cả nhà dùng chung cửa cuốn). Không có bảng `homes`: muốn nhiều nhà về sau chỉ cần thêm cột `home_id` + sửa 2 hàm trong `core/household.py`, không đụng endpoint nào. Vai/grant đọc từ DB **mỗi request** ⇒ duyệt/đổi vai/chặn có hiệu lực ở request kế, không bắt đăng nhập lại (khác với nhét role vào JWT). Thiết bị ngoài khu trả **403 chứ không 404** — trong nhà không cần giấu nhau. `zone_id IS NULL` = "hộp thư đến", rơi ra miễn phí từ `INNER JOIN` nên không có case đặc biệt.
- **⚠️ Isolate nền cần APP-TOKEN, không dùng được token Supabase**: `widgetBackgroundCallback` và shortcut handler chạy ở **isolate riêng**, nơi `Supabase.instance` chưa từng init ⇒ Home Widget hiện "Không rõ" và nút bấm **không làm gì, không báo lỗi**. Init Supabase ở đó thì hai isolate refresh song song, mà Supabase **xoay vòng refresh token** ⇒ isolate này vô hiệu hóa token của isolate kia, cả nhà bị đăng xuất ngẫu nhiên. Cache access token 1h thì hỏng mỗi khi bấm widget sau 1 giờ. Giải: `POST /api/auth/app-token` cấp token dài hạn, lưu SharedPreferences (đọc được ở mọi isolate). Đây là 2 tính năng đầu bảng của app — bật xác thực mà thiếu cái này là hỏng cả hai mà không ai biết.
- **App chưa cấu hình khóa thì BỎ QUA đăng nhập**: `AppConfig.authEnabled` false ⇒ `AuthGate` vào thẳng app với `HouseholdProfile.openHouse`. Khớp với backend đang để xác thực TẮT. Không có nhánh này thì bản build thiếu `--dart-define` kẹt ở màn login vĩnh viễn.
- **Luồng thành viên (1 nhà)**: ai cũng đăng ký được → tài khoản `pending` = "chưa thuộc nhà" (không thấy gì, màn `PendingScreen` nhắc nhờ chủ nhà). Chủ nhà vào Quản trị → Thành viên, **tìm theo tên/email (không phân biệt dấu, `foldVietnamese`)** → "Thêm vào nhà" (chọn vai + khu, 1 bước). Bước này là lớp DUY NHẤT chặn người lạ (Publishable key nằm trong APK ⇒ ai cũng đăng ký được). Nhiều nhà về sau: đề xuất vào nhà bằng MÃ NHÀ (không lộ danh sách nhà) + bảng `homes`/`home_id`, vẫn giữ bước duyệt.
- **Quên mật khẩu dùng MÃ, không dùng link**: mẫu email Supabase "Reset Password" PHẢI chứa `{{ .Token }}` (Authentication → Emails → Templates); link mở trình duyệt về Site URL, app không bắt lại được. SMTP mặc định của Supabase free chỉ gửi vài email/giờ.
- **⚠️ Token Supabase ES256**: project của nhà (tạo 2026) ký access token bằng **ES256** (Settings → JWT Keys), KHÔNG phải HS256. `core/auth._decode_supabase_token` chọn theo `alg` trong header: ES256/RS256 → khóa công khai từ JWKS `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` (cache, kiểm `aud=authenticated` + `iss`); HS256 → `SUPABASE_JWT_SECRET`. Chỉ verify HS256 thì đăng nhập xong mọi request 401. App dùng **Publishable key** (`sb_publishable_...`, thay cho "anon key" cũ) làm `SUPABASE_ANON_KEY`.
- **⚠️ Xác thực TỰ SUY, không mặc định bật**: `AUTH_DISABLED` không đặt ⇒ bật khi có `SUPABASE_URL` hoặc `SUPABASE_JWT_SECRET` (có cách verify token). Thiếu secret thì backend **không verify nổi token**, bật xác thực chỉ làm mọi request 401 và app cả nhà chết — mà service Render tạo tay **KHÔNG đọc `render.yaml`** nên quên set biến ở dashboard là đủ gây sự cố. Có secret → tự bật. Đặt `AUTH_DISABLED=0` tường minh để ép bật (fail closed). Lifespan log to trạng thái mỗi lần boot (`🔒 BẬT` / `🔓 TẮT`).
- **Hẹn giờ (scheduler)**: task asyncio khởi động trong lifespan, tick 30s; mốc kích hoạt khi `now` (giờ VN) vào cửa sổ `[giờ hẹn, +120s)` và fired-date != hôm nay (đánh dấu TRƯỚC khi gửi lệnh — lệnh lỗi không bắn lặp). **Lịch KHOẢNG**: start và end bắn ĐỘC LẬP (restart giữa khoảng vẫn trả thiết bị về trạng thái "sau"); qua đêm (`end < time`) → ngày check end dịch +1 (`_end_days`). **One-shot**: lịch đơn tắt sau start, lịch khoảng tắt sau end; lỡ trọn cửa sổ (server ngủ) → tự tắt + log, tránh bắn nhầm tuần sau. Server được **UptimeRobot ping /health** giữ thức. Scheduler **không khởi động** khi DB lỗi (`db_ready=False`) — tránh tick 30s log stack trace vĩnh viễn. ⚠️ Ổ đĩa Render free là ephemeral — lịch trong SQLite **mất khi redeploy**; đặt `DATABASE_URL` trỏ Postgres để hết (xem `docs/SUPABASE_SETUP.md`). Cần `tzdata` trong requirements (zoneinfo trên Render/Windows).
- **Giọng nói tạo lịch**: local parser gọi `extract_schedule_times` TRƯỚC — câu có giờ ⇒ CHỈ trả `{"intent":"schedule",...}` (tuyệt đối không thi hành ngay; "hẹn 16h30 bật quạt" không được bật quạt luôn); không rõ thiết bị → `[]` cho AI fallback (prompt `ai_parser.py` có few-shot schedule cùng shape). `main.py._create_schedule_from_intent` map verb → cột lịch, `resolve_target_days` ghim thứ + one_shot (giờ đã qua → tự hiểu ngày mai), tạo row qua `_create_schedule_row` (dùng chung POST endpoint), trả bubble "Đã hẹn 16:30 • Chế độ 3". Khoảng không nói hành động kết thúc → mặc định Tắt (cửa mở → đóng; cửa đóng/dừng KHÔNG đoán — an toàn, thành lịch đơn). Test: `backend/tests/` (pytest).
- Pinned shortcut Android là ảnh tĩnh: trạng thái phản ánh qua **icon**, không có badge/text sống. Icon hội tụ về trạng thái THẬT **khi app đang chạy** — `dashboard_tab._syncShortcutIcon` đẩy icon mỗi vòng poll 6s (bắt kịp cả khi điều khiển bằng remote vật lý/app khác), và `_reconcileDoorIcon` chỉnh icon cửa theo trạng thái thật sau khi bấm shortcut. App đóng hoàn toàn thì icon giữ nguyên tới lần app mở kế. Trạng thái sống đầy đủ hơn có ở Home Screen Widget.
- Tên drawable icon shortcut phải khớp CHÍNH XÁC với `ShortcutIcons` (`shortcut_handler.dart`), nếu thiếu → native fallback về `launcher_icon` (logo app).
- **Điều khiển & trạng thái (perf/UX):** endpoint control trả `{status:"error"}` khi thiết bị không nhận lệnh (không còn luôn "success"); connector Tuya/Rojeco dùng `asyncio.to_thread` để không block event loop; status có cache ~3s (`_status_cache`, `?fresh=1` để bỏ cache; **mọi đường điều khiển** — endpoint control, AI executor, scheduler — đều invalidate cache sau lệnh). Card máy lọc/cửa tự poll 6s **chỉ khi tab Home hiển thị + app foreground** (`pollingEnabled`, `WidgetsBindingObserver`); nút có `_sending` chặn double-tap + tô sáng lạc quan `_pendingMode`. ⚠️ Tô sáng lạc quan **reconcile theo giá trị**: chỉ xóa `_pendingMode` khi trạng thái thật khớp mode vừa bấm (hoặc timeout ~10s) — nếu clear mù khi cloud chưa propagate thì highlight sẽ nhảy về mode cũ. Nút cửa luôn bấm được (bỏ khóa), chỉ tô sáng nút đang hoạt động. Card báo trạng thái thật về parent (`onStatusChanged`) để header đếm "Đang bật" đúng.
- **AI executor** nhận cả `action` = `on|off` (AI) lẫn `turn_on|turn_off` (local parser) — sửa lỗi lệnh local "bật/tắt" rơi vào khoảng trống.
- **WebSocket**: `wss://vuhp-smarthome.onrender.com/ws` (`AppConfig.wsUrl`), tự connect khi vào tab AI, chỉ báo "Live" sau khi `channel.ready` (bắt tay xong), giữ tối đa 200 message.
- Server Render free-tier có thể **ngủ** (nếu UptimeRobot gián đoạn) → app `_bootstrap()` ping `/health` (timeout 35s) và hiện "Đang đánh thức máy chủ..." trước khi tải.

- **Đợt 2 — an toàn lệnh (đã sửa, có test `tests/test_security_fixes.py`)**: AI executor chỉ chạm thiết bị trong `device_query` (id AI trả về KHÔNG được tin; kid ép câu sang nhánh AI bằng " và "), brand lấy từ DB; lịch bằng giọng nói theo đúng luật POST /api/schedules (guest không tạo); PATCH lịch đổi `device_id` phải có quyền thiết bị MỚI, chỉ reset fired-date khi giờ THỰC SỰ đổi (đổi tên không làm lịch chạy lại). Tuya: tra category lỗi → **không gửi lệnh** (từng coi là cửa → máy bơm nhận `control:open`), timeout 15s mọi call. "Tắt hết" chỉ tắt máy lọc + công tắc; "bật hết" không đoán. Kịch bản có MỞ CỬA: app hỏi xác nhận, giọng nói từ chối.
- **Test backend qua HTTP** dùng fixture `api` trong `tests/conftest.py`: đăng nhập theo vai + thay `execute_schedule_action`, `parse_command_with_ai` VÀ `device_manager.get_connector` bằng bản ghi giả — **không test nào được gửi lệnh tới thiết bị thật** (nhà có thể đang không có người).
- Còn ngoài phạm vi (biết, chưa sửa): SQLAlchemy đồng bộ chạy trên event loop (Supabase Tokyo ⇒ mỗi query chặn loop); race cache trạng thái 3s (poll bắt đầu trước lệnh có thể ghi đè cache cũ).

## Lệnh hay dùng

```bash
# Backend
cd backend && uvicorn app.main:app --reload
# Frontend
cd frontend && flutter pub get && flutter run
cd frontend && dart analyze
cd frontend && flutter test
cd frontend && flutter build apk --debug
# Build kèm khóa Supabase: khóa nằm ở frontend/supabase.json (gitignore, mẫu supabase.example.json)
cd frontend && flutter build apk --release --dart-define-from-file=supabase.json
```
