# Structure — Cây thư mục & vai trò file

> Cập nhật qua `/sync-docs`. Mỗi entry là 1 file/thư mục + comment ngắn mô tả mục đích.

## Backend (`backend/`)

```
backend/
├── app/
│   ├── main.py                     # FastAPI app: endpoints (devices/control/status/ai/schedules), init_db() + lifespan (khởi tạo DB → connectors → scheduler task), cờ db_ready, middleware đo thời gian
│   ├── core/
│   │   ├── auth.py                 # Verify JWT Supabase -> CurrentUser; CỐ TÌNH sạch model + sạch DB.
│   │   │                           # Token Supabase ES256 qua JWKS (SUPABASE_URL) hoặc HS256 (SUPABASE_JWT_SECRET);
│   │   │                           # auth_disabled() TỰ SUY: bật khi có 1 trong 2, AUTH_DISABLED đặt tường minh thắng
│   │   ├── household.py            # NƠI DUY NHẤT quyết định quyền: provision_member, get_current_member,
│   │   │                           # require_owner, device_query/schedule_query (lọc theo khu),
│   │   │                           # require_device_access (403 vs 404), require_schedule_write
│   │   └── database.py             # Chọn DB theo DATABASE_URL (Postgres/Supabase; rỗng → SQLite smarthome.db): normalize_database_url + make_engine (pool pre_ping/recycle cho Postgres),
│   │                               # SessionLocal + Base + get_db, init_db() = create_all → run_startup_migrations (2 dialect) → verify_schema → enable_rls → seed_defaults
│   ├── models/
│   │   ├── device.py               # DeviceModel (devices: id = id HÃNG làm PK, name, brand, is_active,
│   │   │                           # zone_id FK ON DELETE SET NULL — NULL = "hộp thư đến", category)
│   │   ├── member.py               # MemberModel (members: user_id = auth.users.id dạng text, email,
│   │   │                           # display_name, role owner|adult|kid|guest, status pending|active|blocked)
│   │   ├── zone.py                 # ZoneModel (zones: id, name, sort_order) + MemberZoneAccessModel
│   │   │                           # (member_zone_access: grant theo khu, CHỈ cho kid/guest)
│   │   ├── scene.py                # SceneModel (scenes: name, icon, actions JSON đã chuẩn hóa, created_by) — kịch bản của cả nhà
│   │   └── schedule.py             # ScheduleModel (bảng schedules: time HH:MM, days CSV, action, last_fired_date + lịch KHOẢNG end_time/end_action_*/last_end_fired_date, one_shot, created_by)
│   └── services/
│       ├── base_connector.py       # Lớp trừu tượng: connect/turn_on/turn_off/get_device_state (+set_mode tùy chọn)
│       ├── connector_manager.py    # device_manager: register_connector / get_connector theo brand
│       ├── tuya_connector.py       # Tuya Cloud — cửa cuốn (control open/close/stop; trạng thái từ shadow/properties có thời điểm) + công tắc (switch_1, tự nhận theo category Tuya); credential từ env
│       ├── vesync_connector.py     # VeSync — máy lọc khí (mode, speed)
│       ├── rojeco_connector.py     # Rojeco — máy cho ăn: state = online + feed_state + last_feed (feed_report); credential từ env
│       ├── device_actions.py       # normalize_action: whitelist hành động theo LOẠI thiết bị cho AI/lịch giọng nói/kịch bản
│       ├── local_parser.py         # parse_command_locally: lệnh đơn giản không cần AI; câu CÓ GIỜ → intent schedule (không thi hành ngay)
│       ├── vn_time_parser.py       # extract_schedule_times: parse giờ tiếng Việt (16h30, 4 giờ chiều, từ X đến Y, mai, mỗi ngày) + resolve_target_days
│       ├── ai_parser.py            # parse_command_with_ai: gọi LLM (OpenRouter) cho câu phức (có few-shot intent schedule); client lazy (thiếu key vẫn boot)
│       ├── scheduler.py            # scheduler_loop: vòng lặp Hẹn giờ (tick 30s, grace 120s, TZ Asia/Ho_Chi_Minh); bắn start+end độc lập, qua đêm _end_days +1, one-shot tự tắt
│       └── automation_engine.py    # Automation rules (đang đóng băng, không import trong main.py)
├── docs/
│   ├── supabase_schema.sql         # DDL Postgres idempotent (zones, members, member_zone_access, devices, schedules
│   │                               # + index + seed 3 thiết bị giữ NGUYÊN id + khu 'Nhà' + ENABLE RLS); chạy 1 lần trong SQL Editor
│   └── SUPABASE_SETUP.md           # Hướng dẫn 5 bước tạo Supabase → lấy Session pooler (IPv4) → set DATABASE_URL trên Render → verify; kèm bảng sự cố thường gặp
├── tests/
│   ├── test_vn_time_parser.py      # pytest bảng ví dụ parse giờ + resolve_target_days
│   ├── test_scheduler_helpers.py   # pytest _is_time_due/_is_time_missed/_end_days (grace, thứ, qua đêm)
│   ├── test_database_schema.py     # pytest chọn DB theo env, seed/idempotent/không ghi đè, migration cột, verify_schema, RLS no-op trên SQLite
│   ├── test_household_scope.py     # pytest ma trận quyền: device_query theo khu, 403-vs-404, pending/blocked,
│                                   # lịch lọc theo thiết bị chứ không theo người tạo, quy tắc bật/tắt xác thực,
│                                   # + test qua HTTP để bắt lỗi QUÊN GẮN dependency vào endpoint
│   ├── test_switch_device.py       # pytest máy bơm (công tắc Tuya) + cửa cuốn: parser chọn theo LOẠI, bẫy 'tăng áp'/'ăn', switch_1, cửa theo thời gian
│   ├── conftest.py                 # fixture `api`: đăng nhập theo vai, MỌI lệnh tới thiết bị bị ghi lại (không gửi thật)
│   ├── test_security_fixes.py      # vượt quyền AI/lịch/PATCH, action lạ → 400, Tuya không rõ loại không gửi, 'tắt hết'
│   ├── test_auth_jwks.py           # verify ES256 qua JWKS (khóa EC tự sinh, không gọi mạng), HS256 cũ, app-token, alg none -> 401
│   ├── test_profile.py             # PATCH /api/me chỉ sửa chính mình, validate tên/màu
│   ├── test_shared_zones_scenes.py # khu dùng chung, kịch bản (quyền tạo/chạy, bỏ qua ngoài khu), kịch bản bằng giọng nói
│   └── test_rojeco_state.py        # pytest map online/feed_state/feed_report -> trạng thái máy cho ăn (stub openapi, không gọi mạng)
├── .env                            # Credential thật (VESYNC_*, TUYA_*, OPENROUTER_API_KEY, DATABASE_URL,
│                                   # SUPABASE_JWT_SECRET, ADMIN_EMAILS, AUTH_DISABLED) — gitignored
├── .env.example                    # Mẫu biến môi trường (có DATABASE_URL + ghi chú bẫy Session pooler)
├── requirements.txt                # Python deps THẬT (UTF-8; tzdata cho zoneinfo, PyJWT + psycopg2-binary 2.9.11, pytest + httpx; KHÔNG còn google-*)
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
├── lib/
│   ├── main.dart                   # Entry: khởi động app, đăng ký ShortcutHandler, MaterialApp + appNavigatorKey, 3 tab (Home/AI/Hẹn giờ) + isVisible cho Dashboard
│   ├── core/
│   │   ├── config.dart             # AppConfig: baseUrl / wsUrl / timeout — nơi DUY NHẤT khai báo địa chỉ backend
│   │   │                           # + supabaseUrl/anonKey qua --dart-define; authEnabled=false ⇒ app bỏ qua đăng nhập
│   │   ├── household_api.dart      # Zone/Member model + CRUD khu vực, duyệt/đổi vai/cấp khu, gán thiết bị vào khu
│   │   ├── auth_service.dart       # accessToken() Supabase → fallback app-token (isolate nền), headers() ném
│   │   │                           # NotAuthenticatedException, handleUnauthorized(); HouseholdProfile + fetchMe()
│   │   ├── device_api.dart         # HTTP client: fetchDevices / fetchStatus / sendMode / sendAction + PurifierCycle
│   │   ├── device_type.dart        # deviceTypeOf(name, category:): category backend thắng, fallback suy từ tên; deviceCategoryLabels (nơi duy nhất)
│   │   ├── scene_api.dart          # Scene/SceneAction model + SceneApi: fetch/save/delete/run (SceneRunResult.summary)
│   │   ├── zone_groups.dart        # zoneGroupsOf/devicesInZone: gom thiết bị theo khu cho chip lọc dashboard (thuần dữ liệu)
│   │   ├── theme_controller.dart   # ThemeMode Hệ thống/Sáng/Tối, lưu SharedPreferences, mặc định Tối
│   │   ├── voice_feedback.dart     # TTS vi-VN đọc phản hồi trợ lý + summarize(execution_results); bật/tắt ở Hồ sơ
│   │   ├── avatar.dart             # UserAvatar (chữ cái đầu + màu tự chọn/ổn định theo user_id)
│   │   ├── schedule_api.dart       # Schedule model + ScheduleApi: fetch/create/update/delete/runNow (/api/schedules)
│   │   ├── device_order.dart       # Lưu/áp thứ tự hiển thị thiết bị (kéo-thả) vào SharedPreferences (cục bộ)
│   │   ├── widget_service.dart      # Đẩy trạng thái lên App Widget + callback nền xử lý nút widget (home_widget)
│   │   ├── shortcut_service.dart   # Singleton: MethodChannel 'smarthome/shortcuts' ↔ Android; quick_actions iOS; pin/update/consume action
│   │   ├── shortcut_handler.dart   # Điều phối khi bấm shortcut (purifier cycle / door toggle / feeder); ShortcutIcons map trạng thái→drawable; appNavigatorKey
│   │   └── websocket_provider.dart # Kết nối WebSocket wss (AppConfig.wsUrl); Live chỉ sau channel.ready; cap 200 msg
│   ├── screens/
│   │   ├── admin_screen.dart       # 2 tab quản trị: Thành viên (pending ghim đầu) + Khu vực (CRUD + gán thiết bị,
│   │   │                           # pseudo-zone "Chưa phân khu" ghim cuối để thiết bị mới import không mất dấu;
│   │   │                           # chạm dòng thiết bị → chọn loại/category)
│   │   ├── auth_gate.dart          # 5 trạng thái loading|signedOut|pending|offline|ready; chọn màn hiển thị
│   │   ├── login_screen.dart       # Đăng nhập/đăng ký email+mật khẩu (Supabase Auth), dịch lỗi sang tiếng Việt
│   │   ├── pending_screen.dart     # Màn chờ chủ nhà duyệt + OfflineScreen (mất mạng ≠ hết phiên)
│   │   ├── dashboard_tab.dart      # UI danh sách thiết bị, nút điều khiển + nút "Tạo icon xử lý nhanh"; poll pause theo isVisible/lifecycle
│   │   ├── ai_assistant_tab.dart   # Trợ lý giọng nói (speech-to-text → /api/ai/parse)
│   │   ├── schedule_tab.dart       # Tab Hẹn giờ: danh sách lịch + form thêm/sửa (bottom sheet)
│   │   ├── profile_screen.dart     # Hồ sơ & giao diện: tên, màu avatar, vai/khu, sáng/tối, đọc phản hồi, đăng xuất
│   │   ├── scene_editor_screen.dart # Tạo/sửa kịch bản: tên, icon, hành động theo loại (kéo-thả thứ tự); sceneOpensDoor()
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
