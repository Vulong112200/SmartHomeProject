# Features — Danh sách chức năng & trạng thái

> Cập nhật qua `/sync-docs`. Mỗi feature có format chuẩn: **Status / Backend / Frontend / Key logic**.

## Format chuẩn

```
### <Tên feature>
- **Status:** 📋 planned | 🚧 in progress | ✅ done
- **Backend:** model · service · endpoints liên quan
- **Frontend:** core · screens · widgets · native
- **Key logic:** điểm logic quan trọng/dễ sai
```

---

## Features

### Quản lý thiết bị (devices)
- **Status:** ✅ done
- **Backend:** `DeviceModel` (`models/device.py`) · `/api/devices` GET/POST/DELETE (`main.py:118-155`).
- **Frontend:** `device_api.dart` · `dashboard_tab.dart` (list + card).
- **Key logic:** DeviceModel chỉ có id/name/brand/is_active — KHÔNG có icon/category; loại thiết bị suy từ `brand` phía client (`_isAirPurifier`/`_isFeeder`/`_isCurtain` trong dashboard).

### Điều khiển bật/tắt & chế độ
- **Status:** ✅ done
- **Backend:** `/api/test-control/{brand}/{id}?action=` và `/mode?mode=` (`main.py:160-186`) → connector `turn_on/turn_off/set_mode`.
- **Frontend:** `DeviceApi.sendMode` / control · nút mode trong `dashboard_tab.dart`.
- **Key logic:** cửa cuốn backend tự chèn `stop` trước open/close; mode phụ thuộc brand (tuya: open/close/stop; vesync: low/med/high/auto/sleep/off).

### Trạng thái sống thiết bị
- **Status:** ✅ done
- **Backend:** `/api/devices/{brand}/{id}/status` (`main.py:191`) → `connector.get_device_state`.
- **Frontend:** `DeviceApi.fetchStatus` (`device_api.dart:14`) — dùng ở dashboard & shortcut handler.
- **Key logic:** shape khác nhau theo brand; field chung là `status` (ON/OFF/offline). Tuya thêm `door_state`/`position`; VeSync thêm `mode`/`speed`. ⚠️ Rojeco stub luôn "ON".

### Trợ lý giọng nói (AI)
- **Status:** ✅ done
- **Backend:** `/api/ai/parse` (`main.py:209`) — firewall từ khóa thiết bị → local parser (câu đơn) hoặc AI (câu phức có "và/rồi/với/nhưng") → thực thi song song `asyncio.gather`.
- **Frontend:** `ai_assistant_tab.dart` (speech-to-text) · `chat_bubble.dart`.
- **Key logic:** câu không chứa từ khóa thiết bị bị chặn sớm (không gọi AI); local parser ưu tiên để tiết kiệm chi phí LLM.

### Home-screen Shortcut (icon xử lý nhanh)
- **Status:** ✅ done
- **Backend:** dùng lại `/status` + `/mode`.
- **Frontend:** `shortcut_service.dart` (MethodChannel `smarthome/shortcuts`, quick_actions iOS) · `shortcut_handler.dart` (handle + `ShortcutIcons`) · `MainActivity.kt` (buildShortcut/resolveIcon/pin/update) · `res/drawable/ic_*`.
- **Key logic:**
  - Icon phản ánh trạng thái: `ShortcutIcons.purifier/door/feeder` map trạng thái → tên drawable; native `resolveIcon()` tra theo tên trong `drawable`/`mipmap`, thiếu → fallback `launcher_icon`. **Các drawable ic_purifier_*/ic_door_*/ic_feeder phải tồn tại** (đã tạo).
  - Khi bấm: purifier/door đọc trạng thái thật (`fetchStatus`) → tính bước kế → thực thi → `updateShortcutIcon` cho khớp; feeder/door open/close chỉ hỏi xác nhận.
  - ⚠️ Giới hạn: pinned shortcut là ảnh tĩnh, không badge/text sống; trạng thái chỉ cập nhật lúc bấm (không tự refresh nền). Một số launcher cache icon pinned. iOS quick action vẫn dùng logo app.

### Automation engine
- **Status:** 📋 planned (đóng băng)
- **Backend:** `automation_engine.py` — bị comment trong `main.py:105-113`.
- **Key logic:** chưa kích hoạt; giữ nguyên cho phát triển sau.

---

## Bảng trạng thái Database

| Table | Status | Ghi chú |
|---|---|---|
| devices (`DeviceModel`) | ✅ | id, name, brand, is_active. Thiếu icon/category. |
