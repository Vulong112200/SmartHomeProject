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
- **Frontend:** `device_api.dart` (`fetchDevices`/`fetchStatus`/`sendMode`/`sendAction`) · `dashboard_tab.dart` (list + card).
- **Key logic:** DeviceModel chỉ có id/name/brand/is_active — KHÔNG có icon/category; loại thiết bị suy từ TÊN phía client (`_isAirPurifier`='lọc', `_isFeeder`='mèo'/'ăn', `_isCurtain`='cửa'). Card máy lọc & cửa có nhãn trạng thái sống (`statusLabel`) đọc từ `/status`.

### Điều khiển bật/tắt & chế độ
- **Status:** ✅ done
- **Backend:** `/api/test-control/{brand}/{id}?action=` và `/mode?mode=` (`main.py`) → connector `turn_on/turn_off/set_mode`.
- **Frontend:** `DeviceApi.sendMode`/`sendAction` · nút mode + switch trong `dashboard_tab.dart`.
- **Key logic:**
  - Endpoint kiểm tra `bool` connector trả về — lệnh thất bại → `{status:"error"}` (không còn luôn "success"). `DeviceApi._isOk` đọc `body['status']` chứ không chỉ HTTP 200.
  - Frontend: `_sending` chặn double-tap; `_pendingMode` tô sáng lạc quan nút vừa bấm. **Reconcile theo giá trị**: `_refreshStatus` chỉ xóa `_pendingMode` khi `_currentModeValue(status thật)` KHỚP mode vừa bấm (hoặc quá hạn `_pendingSince` ~10s) → highlight KHÔNG nhảy về mode cũ khi cloud chưa propagate. `_refreshAfterCommand` poll lại nhiều nhịp (~0.7/1.3/2/3s) với `fresh=true` (bỏ cache), dừng sớm khi đã khớp.
  - Nút cửa (Mở/Dừng/Đóng) KHÔNG bị khóa — luôn bấm được; tô sáng nút khớp `door_state` (`activeDoorMode`). Backend tự chèn `stop` trước open/close nên an toàn.
  - Connector Tuya/Rojeco dùng `asyncio.to_thread` cho call HTTP đồng bộ → không block event loop. Mode phụ thuộc brand (tuya: open/close/stop; vesync: low/med/high/auto/sleep/off).

### Trạng thái sống thiết bị
- **Status:** ✅ done
- **Backend:** `/api/devices/{brand}/{id}/status` (`main.py`, opt `?fresh=1` bỏ cache) → `connector.get_device_state`; cache in-memory TTL ~3s (`_status_cache`), tự xóa sau mỗi lệnh điều khiển.
- **Frontend:** `DeviceApi.fetchStatus(brand, id, {fresh})` (`device_api.dart`) — dùng ở dashboard & shortcut handler; card máy lọc/cửa tự động poll `Timer.periodic(6s)` (dùng cache), refresh sau lệnh dùng `fresh:true`.
- **Key logic:** shape khác nhau theo brand; field chung là `status` (ON/OFF/offline). Tuya thêm `door_state`/`position`; VeSync thêm `mode`/`speed`. ⚠️ Rojeco stub luôn "ON".
  - VeSync connector viết cho pyvesync 3.4.2: `_read()` ưu tiên `purifier.state.*` (tránh property deprecated), bọc try/except. `set_mode` ưu tiên API mới `set_fan_speed`/`set_auto_mode`/`set_sleep_mode` (fallback hàm cũ), validate theo `purifier.fan_levels`.
  - **Tuya cửa — suy `door_state` từ trạng thái THẬT trên cloud, KHÔNG từ lịch sử lệnh app.** `get_device_state` đọc DP status từ cloud rồi ưu tiên theo thứ tự: (1) **vị trí thật** (thử lần lượt `_POSITION_DPS`=`percent_state`/`position`/`curtain_position`/`percent_control`) → 100=open, 0=closed, giữa=partial; (2) **tình trạng thật** (`_WORK_STATE_DPS`=`work_state`/`doorcontrol_state`/`situation_set`/`door_state`) map qua `_WORK_STATE_MAP`; (3) **chỉ khi không có (1)(2)** mới fallback DP `control` (= LỆNH CUỐI echo trên cloud, có thể cũ/kẹt). Không nhận ra DP nào → `unknown` + in cảnh báo `[Tuya Door] ⚠️ ... dps=...`. Tên DP là danh sách ứng viên (hằng số đầu `tuya_connector.py`) — bổ sung tên nếu log báo thiết bị dùng tên khác.

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
  - Khi bấm: purifier/door đọc trạng thái thật (`fetchStatus`) → tính bước kế → thực thi → `updateShortcutIcon` cho khớp; feeder/door open/close chỉ hỏi xác nhận. Cửa: sau `sendMode` set icon lạc quan theo mục tiêu rồi `_reconcileDoorIcon` poll lại `fresh` (~2s) chỉnh icon theo `door_state` THẬT (bắt kịp cả khi lệnh không đạt như ý).
  - **Icon hội tụ theo trạng thái THẬT khi app mở:** `dashboard_tab._syncShortcutIcon` gọi trong vòng poll 6s (`_refreshStatus`) — mỗi lần đọc được trạng thái thật, đẩy `updateShortcutIcon` cho cửa/quạt cho khớp → icon đúng cả khi thiết bị bị điều khiển từ remote vật lý / app khác. Gọi `updateShortcut` cho id chưa pin là **no-op an toàn** (native `ShortcutManagerCompat.updateShortcuts` chỉ ảnh hưởng shortcut đang tồn tại) nên không cần lưu danh sách pinned; có `_lastShortcutIcon` chặn gọi native lặp khi icon không đổi.
  - ⚠️ Giới hạn: pinned shortcut là ảnh tĩnh, không badge/text sống; chỉ cập nhật được **khi app đang chạy** (poll dashboard / lúc bấm). App đóng hoàn toàn + điều khiển bằng remote vật lý → icon vẫn cũ tới lần app mở/poll kế. Một số launcher cache icon pinned. iOS quick action vẫn dùng logo app.

### Home Screen Widget (App Widget)
- **Status:** ✅ done
- **Backend:** dùng lại `/api/devices`, `/status`, `/mode`, `/test-control`.
- **Frontend:** `core/widget_service.dart` (đẩy dữ liệu + callback nền) · `DeviceApi.fetchDevices` · `SmartHomeWidgetProvider.kt` · `res/layout/smart_home_widget.xml` · `res/xml/smart_home_widget_info.xml` · package `home_widget` · đăng ký receiver/service trong `AndroidManifest.xml`.
- **Key logic:**
  - 3 khe cố định theo loại: p=máy lọc (contains 'lọc'), c=cửa (contains 'cửa'), f=máy cho ăn (contains 'mèo'/'ăn'). Khe không có thiết bị → ẩn (`{slot}_visible`).
  - Dữ liệu đẩy qua `HomeWidget.saveWidgetData` (string), vẽ lại bằng `updateWidget(qualifiedAndroidName: com.example.frontend.SmartHomeWidgetProvider)`.
  - Nút bấm → `HomeWidgetBackgroundIntent` (URI `smarthome://action?type&brand&id` hoặc `smarthome://refresh`) → `widgetBackgroundCallback` (@pragma vm:entry-point) chạy NỀN, gọi DeviceApi rồi `refreshAll()` cập nhật lại. KHÔNG mở app.
  - App đang mở: `dashboard_tab.fetchDevices` thành công → `WidgetService.refreshAll()` đồng bộ widget.
  - ⚠️ Giới hạn: chỉ hiện 1 thiết bị/loại (nếu có 2 máy lọc chỉ hiện 1). Trạng thái phụ thuộc backend (Render free có thể ngủ → "Không rõ").

### Automation engine
- **Status:** 📋 planned (đóng băng)
- **Backend:** `automation_engine.py` — bị comment trong `main.py:105-113`.
- **Key logic:** chưa kích hoạt; giữ nguyên cho phát triển sau.

---

## Bảng trạng thái Database

| Table | Status | Ghi chú |
|---|---|---|
| devices (`DeviceModel`) | ✅ | id, name, brand, is_active. Thiếu icon/category. |
