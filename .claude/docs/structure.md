# Structure — Cây thư mục & vai trò file

> Cập nhật qua `/sync-docs`. Mỗi entry là 1 file/thư mục + comment ngắn mô tả mục đích.

## Backend (`backend/`)

```
backend/
├── app/
│   ├── main.py                     # FastAPI app: endpoints, startup connectors, /api/ai/parse, middleware đo thời gian
│   ├── core/
│   │   └── database.py             # SQLAlchemy engine + SessionLocal + Base + get_db (SQLite smarthome.db)
│   ├── models/
│   │   └── device.py               # DeviceModel (bảng devices: id, name, brand, is_active)
│   └── services/
│       ├── base_connector.py       # Lớp trừu tượng: connect/turn_on/turn_off/get_device_state (+set_mode tùy chọn)
│       ├── connector_manager.py    # device_manager: register_connector / get_connector theo brand
│       ├── tuya_connector.py       # Tuya Cloud — cửa cuốn/rèm (control open/close/stop, position 0-100)
│       ├── vesync_connector.py     # VeSync — máy lọc khí (mode, speed)
│       ├── rojeco_connector.py     # Rojeco — máy cho ăn (get_device_state STUB luôn "ON")
│       ├── local_parser.py         # parse_command_locally: bắt lệnh đơn giản không cần AI
│       ├── ai_parser.py            # parse_command_with_ai: gọi LLM (OpenRouter) cho câu phức
│       └── automation_engine.py    # Automation rules (đang đóng băng, comment trong main.py)
├── smarthome.db                    # SQLite DB (gitignored)
└── (requirements.txt ở root repo)
```

## Frontend (`frontend/`)

```
frontend/
├── lib/
│   ├── main.dart                   # Entry: khởi động app, đăng ký ShortcutHandler, MaterialApp + appNavigatorKey, tab layout
│   ├── core/
│   │   ├── device_api.dart         # HTTP client: fetchStatus / sendMode / control tới backend
│   │   ├── shortcut_service.dart   # Singleton: MethodChannel 'smarthome/shortcuts' ↔ Android; quick_actions iOS; pin/update/consume action
│   │   ├── shortcut_handler.dart   # Điều phối khi bấm shortcut (purifier cycle / door toggle / feeder); ShortcutIcons map trạng thái→drawable; appNavigatorKey
│   │   └── websocket_provider.dart # Kết nối WebSocket /ws
│   ├── screens/
│   │   ├── dashboard_tab.dart      # UI danh sách thiết bị, nút điều khiển + nút "Tạo icon xử lý nhanh"
│   │   ├── ai_assistant_tab.dart   # Trợ lý giọng nói (speech-to-text → /api/ai/parse)
│   │   └── chat_bubble.dart        # Widget bong bóng chat cho AI tab
│   └── theme/
│       ├── app_colors.dart         # Bảng màu
│       └── app_theme.dart          # ThemeData
└── android/app/src/main/
    ├── kotlin/com/example/frontend/MainActivity.kt   # MethodChannel: pinShortcut/updateShortcut/getInitialAction; buildShortcut + resolveIcon
    ├── AndroidManifest.xml                            # icon launcher_icon, MainActivity singleTop exported
    └── res/
        ├── drawable/ic_purifier_{off,on,low,med,high,auto,sleep}.xml  # icon máy lọc theo trạng thái (vector)
        ├── drawable/ic_door_{open,closed}.xml                         # icon cửa cuốn theo trạng thái (vector)
        ├── drawable/ic_feeder.xml                                     # icon máy cho ăn (vector)
        └── mipmap-*/launcher_icon.png, ic_launcher.png               # logo app
```
