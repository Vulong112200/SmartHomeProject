# Structure — Cây thư mục & vai trò file

> Cập nhật qua `/sync-docs`. Mỗi entry là 1 file/thư mục + comment ngắn mô tả mục đích.

## Backend (`backend/`)

```
backend/
├── app/
│   ├── main.py                     # FastAPI app: endpoints (devices/control/status/ai/schedules, hầu hết đã auth+scope user_id), lifespan (connectors + scheduler task), middleware đo thời gian
│   ├── core/
│   │   ├── database.py             # Chọn engine SQLite (mặc định) hoặc Postgres/Supabase (DATABASE_URL) + SessionLocal + Base + get_db + init_db + run_startup_migrations (ALTER TABLE, chỉ SQLite)
│   │   ├── auth.py                 # get_current_user/require_admin: verify JWT HS256 Supabase (SUPABASE_JWT_SECRET); AUTH_DISABLED=1 bypass cho dev local
│   │   └── crypto.py                # encrypt_json/decrypt_json: mã hóa credential nhà cung cấp (Fernet, khóa FERNET_KEY)
│   ├── models/
│   │   ├── device.py               # DeviceModel (bảng devices: id vendor device id, user_id, name, brand, category, is_active, sort_order, created_at)
│   │   ├── schedule.py             # ScheduleModel (bảng schedules: user_id, time HH:MM, days CSV, action, last_fired_date + lịch KHOẢNG end_time/end_action_*/last_end_fired_date, one_shot)
│   │   └── vendor_account.py       # VendorAccountModel (bảng vendor_accounts: tài khoản nhà cung cấp đã liên kết — VeSync credentials_encrypted, Tuya tuya_uid). Ghi qua /api/vendor/vesync/connect + /api/admin/vendor/tuya/assign
│   └── services/
│       ├── base_connector.py       # Lớp trừu tượng: connect/turn_on/turn_off/get_device_state (+set_mode tùy chọn)
│       ├── connector_manager.py    # device_manager: register_connector / get_connector theo brand (singleton Tuya/Rojeco)
│       ├── connector_factory.py    # get_user_connector(db, user_id, brand): Tuya/Rojeco → singleton chung; VeSync → connector per-user (cache _vesync_cache, credential giải mã từ vendor_accounts). discover_vesync (dùng bởi /api/vendor/vesync/connect) + invalidate_user (khi đổi credential)
│       ├── tuya_connector.py       # Tuya Cloud — cửa cuốn/rèm (control open/close/stop, position 0-100); credential từ env; + list_app_users/list_user_devices (discovery, chưa nối endpoint)
│       ├── vesync_connector.py     # VeSync — máy lọc khí (mode, speed); + list_devices() (discovery, chưa nối endpoint)
│       ├── rojeco_connector.py     # Rojeco — máy cho ăn (get_device_state STUB luôn "ON"); credential từ env
│       ├── local_parser.py         # parse_command_locally: lệnh đơn giản không cần AI; câu CÓ GIỜ → intent schedule (không thi hành ngay)
│       ├── vn_time_parser.py       # extract_schedule_times: parse giờ tiếng Việt (16h30, 4 giờ chiều, từ X đến Y, mai, mỗi ngày) + resolve_target_days
│       ├── ai_parser.py            # parse_command_with_ai: gọi LLM (OpenRouter) cho câu phức (có few-shot intent schedule); client lazy (thiếu key vẫn boot)
│       ├── scheduler.py            # scheduler_loop: vòng lặp Hẹn giờ (tick 30s, grace 120s, TZ Asia/Ho_Chi_Minh); execute_schedule_action nay nhận (db, user_id, ...) để resolve connector theo user; bắn start+end độc lập, qua đêm _end_days +1, one-shot tự tắt
│       └── automation_engine.py    # Automation rules (đang đóng băng, không import trong main.py)
├── tests/
│   ├── test_vn_time_parser.py      # pytest bảng ví dụ parse giờ + resolve_target_days
│   └── test_scheduler_helpers.py   # pytest _is_time_due/_is_time_missed/_end_days (grace, thứ, qua đêm)
├── docs/
│   ├── supabase_schema.sql         # Schema Postgres (profiles/vendor_accounts/devices/schedules + RLS policies owner-or-admin)
│   └── SUPABASE_SETUP.md           # Hướng dẫn tạo project Supabase, lấy khóa, điền .env, migrate dữ liệu SQLite cũ
├── .env                            # Credential thật (TUYA_*, OPENROUTER_API_KEY, DATABASE_URL, SUPABASE_JWT_SECRET, FERNET_KEY, ADMIN_EMAILS, AUTH_DISABLED) — gitignored
├── .env.example                    # Mẫu biến môi trường
├── requirements.txt                # Python deps (UTF-8; tzdata cho zoneinfo; psycopg2-binary cho Postgres; PyJWT cho verify token)
└── smarthome.db                    # SQLite DB (dùng khi KHÔNG đặt DATABASE_URL)
```

## Frontend (`frontend/`)

```
frontend/
├── lib/
│   ├── main.dart                   # Entry: khởi động app, đăng ký ShortcutHandler, MaterialApp + appNavigatorKey, 3 tab (Home/AI/Hẹn giờ) + isVisible cho Dashboard
│   ├── core/
│   │   ├── config.dart             # AppConfig: baseUrl / wsUrl / timeout + supabaseUrl/anonKey — nơi DUY NHẤT khai báo cấu hình
│   │   ├── auth_service.dart       # Bọc Supabase Auth (init/signIn/signUp/signOut) + authHeaders() gắn Bearer token + fetchMe()
│   │   ├── vendor_api.dart         # Client cho /api/vendor/*, /api/devices/import, /api/admin/* (khám phá & quản trị)
│   │   ├── device_api.dart         # HTTP client: fetchDevices / fetchStatus / sendMode / sendAction + PurifierCycle (đã gắn Bearer token)
│   │   ├── device_type.dart        # deviceTypeOf(name): suy loại thiết bị từ tên (nơi duy nhất, dùng chung dashboard/widget/schedule)
│   │   ├── schedule_api.dart       # Schedule model + ScheduleApi: fetch/create/update/delete/runNow (/api/schedules)
│   │   ├── device_order.dart       # Lưu/áp thứ tự hiển thị thiết bị (kéo-thả) vào SharedPreferences (cục bộ)
│   │   ├── widget_service.dart      # Đẩy trạng thái lên App Widget + callback nền xử lý nút widget (home_widget)
│   │   ├── shortcut_service.dart   # Singleton: MethodChannel 'smarthome/shortcuts' ↔ Android; quick_actions iOS; pin/update/consume action
│   │   ├── shortcut_handler.dart   # Điều phối khi bấm shortcut (purifier cycle / door toggle / feeder); ShortcutIcons map trạng thái→drawable; appNavigatorKey
│   │   └── websocket_provider.dart # Kết nối WebSocket wss (AppConfig.wsUrl); Live chỉ sau channel.ready; cap 200 msg
│   ├── screens/
│   │   ├── login_screen.dart       # Đăng nhập/đăng ký email+mật khẩu (Supabase Auth); AuthGate ở main.dart điều hướng
│   │   ├── dashboard_tab.dart      # UI danh sách thiết bị + nút "Tạo icon xử lý nhanh" + nút "Thêm thiết bị" + menu tài khoản (đăng xuất/Quản trị); poll pause theo isVisible/lifecycle
│   │   ├── add_device_screen.dart  # Khám phá & chọn thiết bị: VeSync (email/pass→liệt kê→import) + Tuya (QR→discover→import)
│   │   ├── admin_screen.dart       # [admin] Tab Người dùng + Tab Tuya liên kết (gán tuya_uid, import hộ user)
│   │   ├── ai_assistant_tab.dart   # Trợ lý giọng nói (speech-to-text → /api/ai/parse)
│   │   ├── schedule_tab.dart       # Tab Hẹn giờ: danh sách lịch + form thêm/sửa (bottom sheet)
│   │   └── chat_bubble.dart        # Widget bong bóng chat cho AI tab
│   └── theme/
│       ├── app_colors.dart         # Bảng màu
│       └── app_theme.dart          # ThemeData
└── android/app/src/main/
    ├── kotlin/com/example/frontend/MainActivity.kt              # MethodChannel: pinShortcut/updateShortcut/getInitialAction; buildShortcut + resolveIcon
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
