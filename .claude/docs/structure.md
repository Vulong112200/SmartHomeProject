# Structure — Cây thư mục & vai trò file

> Cập nhật qua `/sync-docs`. Mỗi entry là 1 file/thư mục + comment ngắn mô tả mục đích.

## Backend (`backend/`)

```
backend/
├── app/
│   ├── main.py                     # FastAPI app: endpoints (devices/control/status/ai/schedules), lifespan (connectors + scheduler task), middleware đo thời gian
│   ├── core/
│   │   └── database.py             # SQLAlchemy engine + SessionLocal + Base + get_db (SQLite smarthome.db)
│   ├── models/
│   │   ├── device.py               # DeviceModel (bảng devices: id, name, brand, is_active)
│   │   └── schedule.py             # ScheduleModel (bảng schedules: hẹn giờ đơn — time HH:MM, days CSV, action, last_fired_date)
│   └── services/
│       ├── base_connector.py       # Lớp trừu tượng: connect/turn_on/turn_off/get_device_state (+set_mode tùy chọn)
│       ├── connector_manager.py    # device_manager: register_connector / get_connector theo brand
│       ├── tuya_connector.py       # Tuya Cloud — cửa cuốn/rèm (control open/close/stop, position 0-100); credential từ env
│       ├── vesync_connector.py     # VeSync — máy lọc khí (mode, speed)
│       ├── rojeco_connector.py     # Rojeco — máy cho ăn (get_device_state STUB luôn "ON"); credential từ env
│       ├── local_parser.py         # parse_command_locally: bắt lệnh đơn giản không cần AI
│       ├── ai_parser.py            # parse_command_with_ai: gọi LLM (OpenRouter) cho câu phức; client lazy (thiếu key vẫn boot)
│       ├── scheduler.py            # scheduler_loop: vòng lặp Hẹn giờ (tick 30s, grace 120s, TZ Asia/Ho_Chi_Minh) + execute_schedule_action
│       └── automation_engine.py    # Automation rules (đang đóng băng, không import trong main.py)
├── .env                            # Credential thật (VESYNC_*, TUYA_*, OPENROUTER_API_KEY) — gitignored
├── .env.example                    # Mẫu biến môi trường
├── requirements.txt                # Python deps (UTF-8; có tzdata cho zoneinfo)
└── smarthome.db                    # SQLite DB
```

## Frontend (`frontend/`)

```
frontend/
├── lib/
│   ├── main.dart                   # Entry: khởi động app, đăng ký ShortcutHandler, MaterialApp + appNavigatorKey, 3 tab (Home/AI/Hẹn giờ) + isVisible cho Dashboard
│   ├── core/
│   │   ├── config.dart             # AppConfig: baseUrl / wsUrl / timeout — nơi DUY NHẤT khai báo địa chỉ backend
│   │   ├── device_api.dart         # HTTP client: fetchDevices / fetchStatus / sendMode / sendAction + PurifierCycle
│   │   ├── device_type.dart        # deviceTypeOf(name): suy loại thiết bị từ tên (nơi duy nhất, dùng chung dashboard/widget/schedule)
│   │   ├── schedule_api.dart       # Schedule model + ScheduleApi: fetch/create/update/delete/runNow (/api/schedules)
│   │   ├── device_order.dart       # Lưu/áp thứ tự hiển thị thiết bị (kéo-thả) vào SharedPreferences (cục bộ)
│   │   ├── widget_service.dart      # Đẩy trạng thái lên App Widget + callback nền xử lý nút widget (home_widget)
│   │   ├── shortcut_service.dart   # Singleton: MethodChannel 'smarthome/shortcuts' ↔ Android; quick_actions iOS; pin/update/consume action
│   │   ├── shortcut_handler.dart   # Điều phối khi bấm shortcut (purifier cycle / door toggle / feeder); ShortcutIcons map trạng thái→drawable; appNavigatorKey
│   │   └── websocket_provider.dart # Kết nối WebSocket wss (AppConfig.wsUrl); Live chỉ sau channel.ready; cap 200 msg
│   ├── screens/
│   │   ├── dashboard_tab.dart      # UI danh sách thiết bị, nút điều khiển + nút "Tạo icon xử lý nhanh"; poll pause theo isVisible/lifecycle
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
