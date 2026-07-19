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
| WS | `/ws` | WebSocket (hiện chỉ echo) |
| GET/HEAD | `/`, `/health` | Health check |

## Database Models (`backend/app/models/device.py`)

- **DeviceModel** (`devices`): `id` (PK, vd `den_phong_khach`), `name`, `brand` (`tuya`\|`vesync`\|`rojeco`), `is_active`.
  - ⚠️ Không có cột `icon`/`category`/`type`. Loại thiết bị suy từ `brand` (+ id/name) phía client.

## Connectors (`backend/app/services/`)

| Brand | Thiết bị | File | Ghi chú |
|---|---|---|---|
| tuya | Cửa cuốn/rèm | `tuya_connector.py` | state: `door_state`/`position` suy từ DP THẬT trên cloud — ưu tiên vị trí thật (`_POSITION_DPS`) → tình trạng thật (`_WORK_STATE_DPS`) → fallback DP `control` (lệnh cuối). Danh sách tên DP là ứng viên, bổ sung nếu log `[Tuya Door] ⚠️` báo tên lạ. |
| vesync | Máy lọc khí | `vesync_connector.py` | state: `mode`, `speed` |
| rojeco | Máy cho ăn thú cưng | `rojeco_connector.py` | ⚠️ `get_device_state` là **stub** luôn trả `"ON"` |

Tất cả kế thừa `base_connector.py`; đăng ký qua `connector_manager.py` (`device_manager`) lúc startup.

## File quan trọng nhất

- `backend/app/main.py` — toàn bộ endpoint + luồng AI parse + startup connectors.
- `frontend/lib/core/shortcut_handler.dart` — điều phối hành vi shortcut + `ShortcutIcons` (map trạng thái → tên drawable).
- `frontend/lib/core/shortcut_service.dart` — MethodChannel `smarthome/shortcuts` ↔ native, quick_actions iOS.
- `frontend/android/.../MainActivity.kt` — build/pin/update shortcut, `resolveIcon()`.
- `frontend/lib/screens/dashboard_tab.dart` — UI thiết bị + nút tạo shortcut + đẩy trạng thái lên widget.
- `frontend/lib/core/widget_service.dart` — đẩy trạng thái lên App Widget + callback nền xử lý nút widget.
- `frontend/android/.../SmartHomeWidgetProvider.kt` — AppWidgetProvider render 3 khe thiết bị.

## Lưu ý an toàn / kỹ thuật

- ⚠️ **Credential hardcode** trong `main.py:91-92` (email/password VeSync) và trong `tuya_connector.py`/`rojeco_connector.py` (ACCESS_ID/KEY) — nên chuyển sang biến môi trường `.env`.
- Pinned shortcut Android là ảnh tĩnh: trạng thái phản ánh qua **icon**, không có badge/text sống. Icon hội tụ về trạng thái THẬT **khi app đang chạy** — `dashboard_tab._syncShortcutIcon` đẩy icon mỗi vòng poll 6s (bắt kịp cả khi điều khiển bằng remote vật lý/app khác), và `_reconcileDoorIcon` chỉnh icon cửa theo trạng thái thật sau khi bấm shortcut. App đóng hoàn toàn thì icon giữ nguyên tới lần app mở kế. Trạng thái sống đầy đủ hơn có ở Home Screen Widget.
- Tên drawable icon shortcut phải khớp CHÍNH XÁC với `ShortcutIcons` (`shortcut_handler.dart`), nếu thiếu → native fallback về `launcher_icon` (logo app).
- **Điều khiển & trạng thái (perf/UX):** endpoint control trả `{status:"error"}` khi thiết bị không nhận lệnh (không còn luôn "success"); connector Tuya/Rojeco dùng `asyncio.to_thread` để không block event loop; status có cache ~3s (`_status_cache`, `?fresh=1` để bỏ cache). Card máy lọc/cửa tự poll 6s; nút có `_sending` chặn double-tap + tô sáng lạc quan `_pendingMode`. ⚠️ Tô sáng lạc quan **reconcile theo giá trị**: chỉ xóa `_pendingMode` khi trạng thái thật khớp mode vừa bấm (hoặc timeout ~10s) — nếu clear mù khi cloud chưa propagate thì highlight sẽ nhảy về mode cũ. Nút cửa luôn bấm được (bỏ khóa), chỉ tô sáng nút đang hoạt động.
- Server Render free-tier có thể **ngủ** → app `_bootstrap()` ping `/health` (timeout 35s) và hiện "Đang đánh thức máy chủ..." trước khi tải.

## Lệnh hay dùng

```bash
# Backend
cd backend && uvicorn app.main:app --reload
# Frontend
cd frontend && flutter pub get && flutter run
cd frontend && dart analyze
cd frontend && flutter build apk --debug
```
