# Structure — Cây thư mục & vai trò file

> Cập nhật qua `/sync-docs`. Mỗi entry là 1 file/thư mục + comment ngắn mô tả mục đích.

## Backend (`backend/`)

```
backend/
├── app/
│   ├── main.py                     # FastAPI app: endpoints (devices/control/status/ai/schedules), init_db() + lifespan (khởi tạo DB → register_default_connectors → scheduler task theo SCHEDULER_ENABLED 1|0|auto), cờ db_ready, middleware đo thời gian
│   ├── core/
│   │   ├── auth.py                 # Verify JWT Supabase -> CurrentUser; CỐ TÌNH sạch model + sạch DB.
│   │   │                           # Token Supabase ES256 qua JWKS (SUPABASE_URL) hoặc HS256 (SUPABASE_JWT_SECRET);
│   │   │                           # auth_disabled() TỰ SUY: bật khi có 1 trong 2, AUTH_DISABLED đặt tường minh thắng
│   │   ├── household.py            # NƠI DUY NHẤT quyết định quyền: provision_member, get_current_member,
│   │   │                           # require_owner, device_query/schedule_query (lọc theo khu),
│   │   │                           # require_device_access (403 vs 404), require_schedule_write,
│   │   │                           # realtime_audience (ai trong các kết nối /ws được nhận sự kiện thiết bị nào / phải bị ngắt),
│   │                           # scheduler_target_device (luật của bộ hẹn giờ: thiết bị còn trong nhà, hãng lấy từ DB)
│   │   └── database.py             # Chọn DB theo DATABASE_URL (Postgres/Supabase; rỗng → SQLite smarthome.db): normalize_database_url → async_database_url (asyncpg/aiosqlite)
│   │                               # + async_connect_args (sslmode→ssl, ssl=require ngoài localhost, 6543 tắt prepared stmt) + make_async_engine (pool 5+5, timeout 10s, pre_ping),
│   │                               # async_engine + AsyncSessionLocal (make_session_factory, expire_on_commit=False) + Base + get_db (async, 1 session/request),
│   │                               # init_db(bind: Engine|Connection) = create_all → run_startup_migrations (2 dialect) → verify_schema → enable_rls → seed_defaults; init_db_async = run_sync trong lifespan
│   ├── models/
│   │   ├── device.py               # DeviceModel (devices: id = id HÃNG làm PK, name, brand, is_active,
│   │   │                           # zone_id FK ON DELETE SET NULL — NULL = "hộp thư đến", category)
│   │   ├── member.py               # MemberModel (members: user_id = auth.users.id dạng text, email,
│   │   │                           # display_name, role owner|adult|kid|guest, status pending|active|blocked,
│   │   │                           # avatar_color, sort_order JSON/JSONB deferred = thứ tự Dashboard riêng từng người)
│   │   ├── zone.py                 # ZoneModel (zones: id, name, sort_order) + MemberZoneAccessModel
│   │   │                           # (member_zone_access: grant theo khu, CHỈ cho kid/guest)
│   │   ├── command_log.py          # CommandLogModel (command_logs: at_ms, device/user ẢNH CHỤP, action_label, source, success NULL = quan sát, ext_id UNIQUE)
│   │   ├── floor_plan.py           # FloorPlanModel (floor_plans: 1 hàng id=1, layout JSON {rooms, doors, devices} theo MÉT, updated_by/at_ms)
│   │   ├── scene.py                # SceneModel (scenes: name, icon, actions JSON đã chuẩn hóa, created_by, conditions JSON|NULL) — kịch bản của cả nhà
│   │   ├── schedule_run.py         # ScheduleRunModel (schedule_runs: 1 hàng / occurrence, UNIQUE(schedule_id, part, occurrence),
│   │   │                           # status claimed|sending|success|retry|failed|rejected|abandoned) + SchedulerHeartbeatModel (scheduler_heartbeats: role api|worker, state)
│   │   └── schedule.py             # ScheduleModel (bảng schedules: time HH:MM, days CSV, action, last_fired_date + lịch KHOẢNG end_time/end_action_*/last_end_fired_date, one_shot, created_by)
│   └── services/
│       ├── base_connector.py       # Lớp trừu tượng: connect/turn_on/turn_off/get_device_state (+set_mode tùy chọn)
│       ├── connector_manager.py    # device_manager: register_connector / get_connector theo brand; register_default_connectors() (Tuya/VeSync/Rojeco — dùng chung API + worker)
│       ├── tuya_connector.py       # Tuya Cloud — cửa cuốn (control open/close/stop; trạng thái từ shadow/properties có thời điểm) + công tắc (switch_1, tự nhận theo category Tuya); credential từ env
│       ├── vesync_connector.py     # VeSync — máy lọc khí (mode, speed)
│       ├── rojeco_connector.py     # Rojeco — máy cho ăn: state = online + feed_state + last_feed (feed_report); credential từ env
│       ├── floor_plan.py           # Sơ đồ 2D thuần dữ liệu: DEFAULT_LAYOUT (2 phòng kích thước thật), sanitize_layout (400 khi hình học sai, bỏ thiết bị lạ, kẹp tọa độ), parse_stored, visible_layout (lọc thiết bị theo quyền)
│       ├── device_actions.py       # normalize_action: whitelist hành động theo LOẠI thiết bị cho AI/lịch giọng nói/kịch bản
│       ├── scene_condition_engine.py # Điều kiện kịch bản: normalize_conditions (lưu), load_stored, evaluate_conditions (time_range + device_state, AND/OR ba giá trị passed|failed|unknown)
│       ├── local_parser.py         # parse_command_locally: lệnh đơn giản không cần AI; câu CÓ GIỜ → intent schedule (không thi hành ngay)
│       ├── vn_time_parser.py       # extract_schedule_times: parse giờ tiếng Việt (16h30, 4 giờ chiều, từ X đến Y, mai, mỗi ngày) + resolve_target_days
│       ├── ai_parser.py            # parse_command_with_ai: gọi LLM (OpenRouter) cho câu phức (có few-shot intent schedule); client lazy (thiếu key vẫn boot)
│       ├── command_log.py          # record(): ghi lệnh hệ thống gửi (lỗi DB không làm hỏng lệnh); action_label theo loại; prune_old 90 ngày
│       ├── device_history.py       # Sự kiện NGOÀI app: nhật ký Tuya (type 5/7, classify_tuya_logs) + VeSync observe_state (bỏ qua nếu RAM recently_sent HOẶC command_logs có lệnh hệ thống ≤60s — thấy cả lệnh của worker)
│       ├── scheduler.py            # Bộ máy Hẹn giờ DÙNG CHUNG (API + worker): ScheduleEngine.tick (tick 30s, grace 120s, TZ Asia/Ho_Chi_Minh; start+end độc lập, qua đêm _end_days +1, one-shot tự tắt)
│       │                           # claim nguyên tử (UPDATE có điều kiện + INSERT schedule_runs UNIQUE), phục hồi hàng kẹt (lease 90s), RETRY_POLICIES theo loại,
│       │                           # normalize_action trước khi gửi, giờ DB (use_db_clock), nhịp tim; run_forever, scheduler_loop (API), scheduler_mode (SCHEDULER_ENABLED); _fire → record + realtime.notify_command
│       ├── realtime.py             # /ws: ConnectionManager (kết nối đã xác thực, gửi có khóa+timeout 5s, heartbeat ping 25s/chết 75s, kiểm lại thành viên 2 phút),
│       │                           # notify_state (phát khi trạng thái ĐỔI, bỏ bản đọc cũ, offline/online), notify_command (chỉ lệnh thành công + đọc lại 1.5s/5s, cửa +32s),
│       │                           # watcher 15s khi có ≥1 kết nối. Sạch DB/quyền: main.py cắm audience/refresh/targets qua configure()
│       └── automation_engine.py    # Automation rules (đang đóng băng, không import trong main.py)
├── worker/                         # Worker Hẹn giờ tại nhà — tiến trình ĐỘC LẬP (không FastAPI): python -m worker [run|once|status]
│   ├── __main__.py                 # CLI; nạp .env (--env-file > WORKER_ENV_FILE > worker/.env > backend/.env) TRƯỚC khi import app.*
│   ├── config.py                   # WorkerConfig từ env: WORKER_DATABASE_URL|DATABASE_URL (bắt buộc; SQLite chỉ khi WORKER_ALLOW_SQLITE=1), WORKER_TICK_SECONDS 5–55, WORKER_LOG_FILE
│   ├── db.py                       # Engine ASYNC RIÊNG (asyncpg, pool 2+1, timeout 10s, command_timeout 30s thay TCP keepalive, pre_ping), check_db async (verify_schema 5 bảng qua run_sync), wait_for_db backoff 5→60s
│   ├── runner.py                   # run_worker: log (stdout + file xoay vòng) → chờ DB → connectors → ScheduleEngine(role worker, giờ DB) → run_forever; SIGTERM/Ctrl+C dừng sau tick, ghi nhịp tim stopped
│   ├── status.py                   # Sức khỏe (chỉ đọc): DB/schema, lệch đồng hồ, nhịp tim, lần chạy mở/gần đây, lịch sẽ bị từ chối; mã thoát 0/1/2
│   ├── README.md                   # Vận hành: chống trùng, phục hồi, cài đặt, systemd/Task Scheduler, log, mất mạng, cập nhật, CHUYỂN ĐỔI production
│   └── deploy/                     # smarthome-worker.service (systemd), worker.env.example, worker_role.sql (role Postgres quyền tối thiểu + policy RLS riêng)
├── docs/
│   ├── supabase_schema.sql         # DDL Postgres idempotent (zones, members, member_zone_access, devices, schedules, schedule_runs, scheduler_heartbeats
│   │                               # + index + seed 3 thiết bị giữ NGUYÊN id + khu 'Nhà' + ENABLE RLS); chạy 1 lần trong SQL Editor
│   └── SUPABASE_SETUP.md           # Hướng dẫn 5 bước tạo Supabase → lấy Session pooler (IPv4) → set DATABASE_URL trên Render → verify; kèm bảng sự cố thường gặp
├── tests/
│   ├── test_vn_time_parser.py      # pytest bảng ví dụ parse giờ + resolve_target_days
│   ├── test_scheduler_helpers.py   # pytest _is_time_due/_is_time_missed/_end_days (grace, thứ, qua đêm)
│   ├── test_scheduler_engine.py    # bộ máy hẹn giờ: đúng 1 lần, lặp theo thứ, khoảng, qua đêm, claim CAS (ảnh chụp cũ / 8 luồng / 2 worker), phục hồi crash, thử lại theo loại, normalize, mất DB, auto standby
│   ├── test_worker.py              # worker: cấu hình env, không nạp app.main/uvicorn, once trên SQLite tạm, wait_for_db, status mã thoát
│   ├── test_database_schema.py     # pytest chọn DB theo env, seed/idempotent/không ghi đè, migration cột, verify_schema, RLS no-op trên SQLite
│   ├── test_household_scope.py     # pytest ma trận quyền: device_query theo khu, 403-vs-404, pending/blocked,
│                                   # lịch lọc theo thiết bị chứ không theo người tạo, quy tắc bật/tắt xác thực,
│                                   # + test qua HTTP để bắt lỗi QUÊN GẮN dependency vào endpoint
│   ├── test_switch_device.py       # pytest máy bơm (công tắc Tuya) + cửa cuốn: parser chọn theo LOẠI, bẫy 'tăng áp'/'ăn', switch_1, cửa theo thời gian
│   ├── conftest.py                 # fixture `api`: đăng nhập theo vai, MỌI lệnh tới thiết bị bị ghi lại (không gửi thật)
│   ├── test_security_fixes.py      # vượt quyền AI/lịch/PATCH, action lạ → 400, Tuya không rõ loại không gửi, 'tắt hết'
│   ├── test_auth_jwks.py           # verify ES256 qua JWKS (khóa EC tự sinh, không gọi mạng), HS256 cũ, app-token (+ token DEV cấp lúc auth tắt -> 401), alg none -> 401
│   ├── test_profile.py             # PATCH /api/me chỉ sửa chính mình, validate tên/màu
│   ├── test_device_order.py        # members.sort_order: lưu/đọc, khử trùng, lọc ngoài quyền, mỗi tài khoản riêng, giá trị hỏng không làm hỏng API
│   ├── test_shared_zones_scenes.py # khu dùng chung, kịch bản (quyền tạo/chạy, bỏ qua ngoài khu), kịch bản bằng giọng nói
│   ├── test_scene_conditions.py    # điều kiện kịch bản: qua đêm, AND/OR, offline/lỗi/ngoài quyền = unknown, bỏ cache, skipped không gửi lệnh, giọng nói, kịch bản cũ
│   ├── test_command_history.py    # lịch sử: người/nguồn/kết quả, via không giả được, giọng nói/kịch bản/lịch, lọc theo khu, phân loại nhật ký Tuya, VeSync
│   ├── test_floor_plan.py          # sơ đồ: mặc định đúng kích thước, chỉ chủ nhà PUT, kid chỉ thấy thiết bị khu mình, validate hình học, layout hỏng → mặc định, DB cũ được tạo bảng
│   ├── test_realtime.py            # ConnectionManager: phát khi đổi, bản cũ về muộn bị bỏ, offline/online, lọc quyền, kết nối lỗi không lan, lệnh lỗi không phát, heartbeat, watcher + household.realtime_audience
│   ├── test_realtime_ws.py         # /ws qua ASGI thật (cùng loop với HTTP): auth 4401/4403/4429/1013, app/trợ lý/kịch bản/lịch/scheduler → sự kiện đúng người, chặn → ngắt, app cũ chỉ echo
│   └── test_rojeco_state.py        # pytest map online/feed_state/feed_report -> trạng thái máy cho ăn (stub openapi, không gọi mạng)
├── .env                            # Credential thật (VESYNC_*, TUYA_*, OPENROUTER_API_KEY, DATABASE_URL,
│                                   # SUPABASE_JWT_SECRET, ADMIN_EMAILS, AUTH_DISABLED) — gitignored
├── .env.example                    # Mẫu biến môi trường (có DATABASE_URL + ghi chú bẫy Session pooler)
├── requirements.txt                # Python deps THẬT (UTF-8; tzdata cho zoneinfo, PyJWT + asyncpg 0.32.0 + aiosqlite 0.22.1 (psycopg2-binary 2.9.11 còn giữ, không dùng), pytest + httpx; KHÔNG còn google-*)
└── smarthome.db                    # SQLite DB — chỉ dùng khi KHÔNG đặt DATABASE_URL (dev local). Đang bị track trong git nên redeploy Render ghi đè nó.
```

## Root (`./`)

```
./
├── render.yaml                     # Blueprint Render: rootDir backend, build/start command, healthCheckPath /health, PYTHON_VERSION 3.13.5
│                                   # ⚠️ chỉ có tác dụng với service quản lý bằng Blueprint; service tạo tay dùng cấu hình trên dashboard
└── requirements.txt                # CON TRỎ `-r backend/requirements.txt` — KHÔNG phải danh sách thật.
                                    # Trước đây là bản sao UTF-16 lệch phía sau và đã gây sập production (thiếu PyJWT).
```

## Frontend (`frontend/`)

```
frontend/
├── supabase.example.json       # mẫu khóa Supabase cho build (--dart-define-from-file); bản thật supabase.json gitignore
├── lib/
│   ├── main.dart                   # Entry: khởi động app, đăng ký ShortcutHandler, MaterialApp + appNavigatorKey, 4 tab (Home/Sơ đồ/AI/Hẹn giờ) + isVisible cho Dashboard và Sơ đồ
│   ├── core/
│   │   ├── config.dart             # AppConfig: baseUrl / wsUrl / timeout — nơi DUY NHẤT khai báo địa chỉ backend
│   │   │                           # + supabaseUrl/anonKey qua --dart-define; authEnabled=false ⇒ app bỏ qua đăng nhập
│   │   ├── household_api.dart      # Zone/Member model + CRUD khu vực, duyệt/đổi vai/cấp khu, gán thiết bị vào khu
│   │   ├── auth_service.dart       # accessToken() Supabase → fallback app-token (isolate nền), headers() ném
│   │   │                           # NotAuthenticatedException, handleUnauthorized(); HouseholdProfile + fetchMe()
│   │   ├── device_api.dart         # HTTP client: fetchDevices / fetchStatus (+ fetchStatusStamped kèm read_at_ms) / sendMode / sendAction (+ via) + PurifierCycle
│   │   ├── floor_plan.dart         # FloorPlan/PlanRoom/PlanDoor/DevicePlacement (bất biến, mét) + thao tác sửa (kéo/hút/kẹp) + PlanGeometry (mét↔px, 1 tỷ lệ chung) + FloorPlanApi (GET/PUT /api/floor-plan)
│   │   ├── device_status.dart      # Diễn giải /status: describeDeviceStatus (active/idle/moving/offline/unknown + nhãn), currentActionKey, statusConfirms, needsPolling
│   │   ├── device_type.dart        # deviceTypeOf(name, category:): category backend thắng, fallback suy từ tên; deviceCategoryLabels (nơi duy nhất)
│   │   ├── history_api.dart        # HistoryEntry + HistorySource (nơi duy nhất map nguồn → nhãn/icon) + HistoryApi.fetch (timeout 20s)
│   │   ├── scene_api.dart          # Scene/SceneAction/SceneCondition(s) model + SceneApi: fetch/save/delete/run (SceneRunResult.fromResponse — status success|skipped)
│   │   ├── zone_groups.dart        # zoneGroupsOf/devicesInZone: gom thiết bị theo khu cho chip lọc dashboard (thuần dữ liệu)
│   │   ├── theme_controller.dart   # ThemeMode Hệ thống/Sáng/Tối, lưu SharedPreferences, mặc định Tối
│   │   ├── voice_feedback.dart     # TTS vi-VN đọc phản hồi trợ lý + summarize(execution_results); bật/tắt ở Hồ sơ
│   │   ├── avatar.dart             # UserAvatar (chữ cái đầu + màu tự chọn/ổn định theo user_id)
│   │   ├── schedule_api.dart       # Schedule model + ScheduleApi: fetch/create/update/delete/runNow (/api/schedules)
│   │   ├── device_order.dart       # DeviceOrder.apply (sắp theo id) + DeviceOrderSync (debounce 2s, thử lại, bản chờ lưu SharedPreferences) → PATCH /api/me sort_order; cục bộ device_order_v1 khi chưa bật đăng nhập
│   │   ├── widget_service.dart      # Đẩy trạng thái lên App Widget + callback nền xử lý nút widget (home_widget)
│   │   ├── shortcut_service.dart   # Singleton: MethodChannel 'smarthome/shortcuts' ↔ Android; quick_actions iOS; pin/update/consume action
│   │   ├── shortcut_handler.dart   # Điều phối khi bấm shortcut (purifier cycle / door toggle / feeder); ShortcutIcons map trạng thái→drawable; appNavigatorKey
│   │   ├── realtime_service.dart   # RealtimeService.instance: MỘT kết nối /ws (auth frame đầu, live sau connection.ready, pong, backoff 1s→60s ±20%,
│   │   │                           # 4401/4403/4429 chờ 5 phút, watchdog im lặng 70s), DeviceEvent, eventsFor(id), isFresherStatus; RealtimeTransport để test thay
│   │   └── websocket_provider.dart # Lớp Riverpod MỎNG trên RealtimeService (huy hiệu "Live" tab Trợ lý) — không mở kết nối riêng
│   ├── screens/
│   │   ├── admin_screen.dart       # 2 tab quản trị: Thành viên (pending ghim đầu) + Khu vực (CRUD + gán thiết bị,
│   │   │                           # pseudo-zone "Chưa phân khu" ghim cuối để thiết bị mới import không mất dấu;
│   │   │                           # chạm dòng thiết bị → chọn loại/category)
│   │   ├── auth_gate.dart          # 5 trạng thái loading|signedOut|pending|offline|ready; chọn màn hiển thị
│   │   ├── login_screen.dart       # Đăng nhập/đăng ký email+mật khẩu (Supabase Auth), dịch lỗi sang tiếng Việt
│   │   ├── pending_screen.dart     # Màn chờ chủ nhà duyệt + OfflineScreen (mất mạng ≠ hết phiên)
│   │   ├── floor_plan/             # Tab "Sơ đồ" (mặt bằng 2D)
│   │   │   ├── floor_plan_tab.dart       # Màn + FloorPlanDataSource (API thật / giả cho test), poll dự phòng khi hiển thị + /ws không live (live ⇒ áp sự kiện /ws), gửi lệnh + chờ xác nhận, chế độ Sửa (chủ nhà)
│   │   │   ├── floor_plan_painter.dart   # CustomPainter phòng/lưới 1 m/tường/cửa/nhãn kích thước; KHÔNG vẽ thiết bị
│   │   │   ├── plan_device.dart          # PlanDevice, DeviceLive (trạng thái sống/lệnh), DeviceMarker (icon theo trạng thái), icon/màu theo loại
│   │   │   ├── device_control_sheet.dart # Bottom sheet điều khiển 1 thiết bị (deviceActionOptions), hiện kết quả lệnh
│   │   │   └── plan_edit_sheets.dart     # Bảng sửa: phòng (thêm cửa, kích thước), cửa (bề rộng/xóa), bỏ thiết bị, chọn phòng
│   │   ├── dashboard_tab.dart      # UI danh sách thiết bị, nút điều khiển + nút "Tạo icon xử lý nhanh"; thẻ nghe eventsFor(id) của /ws, poll 6s CHỈ khi /ws không live (dự phòng), pause theo isVisible/lifecycle, chặn bản đọc cũ (read_at_ms)
│   │   ├── ai_assistant_tab.dart   # Trợ lý giọng nói (speech-to-text → /api/ai/parse)
│   │   ├── schedule_tab.dart       # Tab Hẹn giờ: danh sách lịch + form thêm/sửa (bottom sheet)
│   │   ├── forgot_password_screen.dart # Quên mật khẩu: email -> mã OTP (verifyOTP recovery) -> mật khẩu mới
│   │   ├── password_field.dart     # PasswordField (nút con mắt) + validateNewPassword + friendlyAuthError (dịch lỗi Supabase)
│   │   ├── history_screen.dart     # Lịch sử điều khiển: nhóm theo ngày, lọc thiết bị, 'Chỉ ngoài app', tải thêm
│   │   ├── help_screen.dart        # Hướng dẫn sử dụng: helpTopics (mục Quản trị chỉ chủ nhà thấy)
│   │   ├── onboarding_screen.dart  # Giới thiệu 4 trang ở lần đầu vào app (cờ onboarding_done_v1)
│   │   ├── profile_screen.dart     # Hồ sơ & giao diện: tên, màu avatar, vai/khu, sáng/tối, đọc phản hồi, đăng xuất
│   │   ├── scene_editor_screen.dart # Tạo/sửa kịch bản: tên, icon, ĐIỀU KIỆN (giờ/trạng thái thiết bị, AND/OR), hành động theo loại (kéo-thả thứ tự); sceneOpensDoor(), describeSceneCondition()
│   │   └── chat_bubble.dart        # Widget bong bóng chat cho AI tab
│   └── theme/
│       ├── app_colors.dart         # AppPalette (ThemeExtension) dark = màu gốc + light; đọc qua context.palette
│       └── app_theme.dart          # lightTheme + darkTheme (gắn AppPalette)
└── android/app/src/main/
    ├── kotlin/com/example/frontend/MainActivity.kt              # MethodChannel: pinShortcut/updateShortcut/getInitialAction; buildShortcut + resolveIcon
    ├── kotlin/com/example/frontend/WidgetRefreshWorker.kt       # WorkManager 15 phút: bắn smarthome://refresh để widget tự làm mới khi app đóng
    ├── kotlin/com/example/frontend/SmartHomeWidgetProvider.kt   # AppWidgetProvider: render 3 khe thiết bị, gắn HomeWidgetBackgroundIntent cho nút
    ├── AndroidManifest.xml                            # launcher_icon; MainActivity singleTop; đăng ký widget provider + home_widget receiver/service
    └── res/
        ├── drawable/ic_purifier_{off,on,low,med,high,auto,sleep}.xml  # icon máy lọc theo trạng thái (vector)
        ├── drawable/ic_door_{open,closed}.xml                         # icon cửa cuốn theo trạng thái (vector)
        ├── drawable/ic_feeder.xml                                     # icon máy cho ăn (vector)
        ├── drawable/widget_background.xml, widget_button_bg.xml       # nền widget + nền nút
        ├── layout/smart_home_widget.xml                              # layout App Widget (header + 3 khe device)
        ├── xml/smart_home_widget_info.xml                            # khai báo appwidget-provider
        └── mipmap-*/launcher_icon.png, ic_launcher.png               # logo app
```
