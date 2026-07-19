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
| Dashboard điều khiển | ✅ | `screens/dashboard_tab.dart` |
| Sắp xếp thứ tự thiết bị (kéo-thả) | ✅ | `screens/dashboard_tab.dart` (`SliverReorderableList`), `core/device_order.dart` (lưu SharedPreferences) |
| Home-screen Shortcut (icon xử lý nhanh) | ✅ | `core/shortcut_service.dart`, `core/shortcut_handler.dart`, `MainActivity.kt`, `res/drawable/ic_*` |
| Home Screen Widget (trạng thái sống + điều khiển nền) | ✅ | `core/widget_service.dart`, `SmartHomeWidgetProvider.kt`, `res/layout/smart_home_widget.xml`, package `home_widget` |
| Hẹn giờ thiết bị (schedule server-side) | ✅ | `services/scheduler.py`, `models/schedule.py`, `main.py` `/api/schedules`, `screens/schedule_tab.dart`, `core/schedule_api.dart` |
| Automation engine | 📋 (đóng băng) | `services/automation_engine.py` (comment trong `main.py`) |

## API Endpoints Summary (`backend/app/main.py`)

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/devices` | Liệt kê thiết bị (DB) |
| POST | `/api/devices` | Thêm thiết bị (query: id, name, brand) |
| DELETE | `/api/devices/{device_id}` | Xóa thiết bị |
| GET | `/api/test-control/{brand}/{device_id}?action=on\|off` | Bật/tắt |
| GET | `/api/test-control/{brand}/{device_id}/mode?mode=...` | Đổi chế độ (open/close/stop/low/high...) |
| GET | `/api/devices/{brand}/{device_id}/status` (opt `?fresh=1`) | **Trạng thái sống** → `{data:{status:ON\|OFF\|offline, door_state, position,...}}`. Có cache ~3s; `fresh=1` bỏ qua cache (dùng sau lệnh điều khiển). |
| POST | `/api/ai/parse` | Parse + thực thi lệnh NL (body `{text}`) |
| GET | `/api/schedules` | Liệt kê lịch hẹn giờ |
| POST | `/api/schedules` | Tạo lịch (body JSON: name, brand, device_id, action_type, action_value, time, days, enabled) |
| PATCH | `/api/schedules/{id}` | Sửa lịch / bật-tắt `enabled` (đổi giờ hoặc bật lại → reset `last_fired_date`) |
| DELETE | `/api/schedules/{id}` | Xóa lịch |
| POST | `/api/schedules/{id}/run` | Chạy NGAY hành động của lịch (test), không đổi `last_fired_date` |
| WS | `/ws` | WebSocket (hiện chỉ echo) |
| GET/HEAD | `/`, `/health` | Health check (UptimeRobot ping giữ server thức) |

## Database Models (`backend/app/models/`)

- **DeviceModel** (`devices`, `device.py`): `id` (PK, vd `den_phong_khach`), `name`, `brand` (`tuya`\|`vesync`\|`rojeco`), `is_active`.
  - ⚠️ Không có cột `icon`/`category`/`type`. Loại thiết bị suy từ TÊN phía client (`core/device_type.dart` — nơi duy nhất).
- **ScheduleModel** (`schedules`, `schedule.py`): `id` (PK int), `name`, `brand`, `device_id`, `action_type` (`on`\|`off`\|`mode`), `action_value` (mode value, null với on/off), `time` (`"HH:MM"` giờ **Asia/Ho_Chi_Minh**), `days` (CSV weekday Python `0`=Thứ2…`6`=CN, rỗng = mỗi ngày), `enabled`, `last_fired_date` (`"YYYY-MM-DD"` chống kích hoạt trùng trong ngày).

## Connectors (`backend/app/services/`)

| Brand | Thiết bị | File | Ghi chú |
|---|---|---|---|
| tuya | Cửa cuốn/rèm | `tuya_connector.py` | state: `door_state`/`position` suy từ DP THẬT trên cloud — ưu tiên vị trí thật (`_POSITION_DPS`) → tình trạng thật (`_WORK_STATE_DPS`) → fallback DP `control` (lệnh cuối). Danh sách tên DP là ứng viên, bổ sung nếu log `[Tuya Door] ⚠️` báo tên lạ. |
| vesync | Máy lọc khí | `vesync_connector.py` | state: `mode`, `speed` |
| rojeco | Máy cho ăn thú cưng | `rojeco_connector.py` | ⚠️ `get_device_state` là **stub** luôn trả `"ON"` |

Tất cả kế thừa `base_connector.py`; đăng ký qua `connector_manager.py` (`device_manager`) lúc startup (lifespan, mỗi connector bọc try/except — 1 hãng lỗi không sập app).

## File quan trọng nhất

- `backend/app/main.py` — toàn bộ endpoint + luồng AI parse + lifespan (connectors + scheduler task).
- `backend/app/services/scheduler.py` — vòng lặp Hẹn giờ (tick 30s, grace 120s, TZ Asia/Ho_Chi_Minh).
- `frontend/lib/core/config.dart` — nơi DUY NHẤT khai báo baseUrl/wsUrl/timeout.
- `frontend/lib/core/shortcut_handler.dart` — điều phối hành vi shortcut + `ShortcutIcons` (map trạng thái → tên drawable).
- `frontend/lib/core/shortcut_service.dart` — MethodChannel `smarthome/shortcuts` ↔ native, quick_actions iOS.
- `frontend/android/.../MainActivity.kt` — build/pin/update shortcut, `resolveIcon()`.
- `frontend/lib/screens/dashboard_tab.dart` — UI thiết bị + nút tạo shortcut + đẩy trạng thái lên widget.
- `frontend/lib/screens/schedule_tab.dart` — tab Hẹn giờ (list + form bottom-sheet).
- `frontend/lib/core/widget_service.dart` — đẩy trạng thái lên App Widget + callback nền xử lý nút widget.
- `frontend/android/.../SmartHomeWidgetProvider.kt` — AppWidgetProvider render 3 khe thiết bị.

## Lưu ý an toàn / kỹ thuật

- **Credential ở biến môi trường**: `backend/.env` (gitignore, mẫu ở `backend/.env.example`) — `VESYNC_EMAIL/PASSWORD`, `TUYA_ACCESS_ID/KEY/API_ENDPOINT`, `OPENROUTER_API_KEY`. Trên Render set trong Dashboard > Environment. Thiếu `OPENROUTER_API_KEY` app vẫn boot (AI client khởi tạo lười, local parser vẫn chạy).
- **Hẹn giờ (scheduler)**: task asyncio khởi động trong lifespan, tick 30s; lịch kích hoạt khi `now` (giờ VN) vào cửa sổ `[giờ hẹn, +120s)` và `last_fired_date != hôm nay` (đánh dấu TRƯỚC khi gửi lệnh — lệnh lỗi không bắn lặp). Server được **UptimeRobot ping /health** giữ thức. ⚠️ Ổ đĩa Render free là ephemeral — lịch trong SQLite **mất khi redeploy** (cân nhắc DB ngoài nếu cần bền). Cần `tzdata` trong requirements (zoneinfo trên Render/Windows).
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
