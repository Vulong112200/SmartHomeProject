# Callflows — Luồng hoạt động chính

> Cập nhật qua `/sync-docs`. Mô tả chuỗi UI → service → backend → connector → thiết bị → response.

## 1. Tạo & bấm Shortcut thiết bị (Android)

**Tạo shortcut:**
```
dashboard_tab.dart: _buildShortcutButton (iconRes = ShortcutIcons.<type>(state))
  → _createShortcut → ShortcutService.pinShortcut(action, label, iconRes)
    → MethodChannel 'smarthome/shortcuts'.invokeMethod('pinShortcut', {id, labels, iconRes, ...action})
      → MainActivity.buildShortcut: tạo ShortcutInfoCompat
           Intent(ACTION_VIEW → MainActivity) + extras(type/brand/deviceId/deviceName)
           setIcon(resolveIcon(iconRes))   # tra drawable theo tên; thiếu → launcher_icon
        → ShortcutManagerCompat.requestPinShortcut  # hệ thống hỏi "thêm vào màn hình chính"
```

**Bấm shortcut trên màn hình chính:**
```
Launch MainActivity với intent extras
  ├─ cold start: getInitialAction → ShortcutService._consumeInitialAction
  └─ đang chạy: onNewIntent → invokeMethod('onShortcutAction', map)
    → ShortcutService._dispatch → ShortcutHandler.handle(action)  (switch theo action.type)
      ├─ purifierCycle: fetchStatus → PurifierCycle.next → apply(/mode) → updateShortcutIcon(step)
      ├─ doorToggle:    fetchStatus → hỏi chiều ngược → sendMode(open/close) → updateShortcutIcon(state)
      ├─ doorOpen/doorClose/feederFeed: _confirm dialog → DeviceApi.sendMode
      └─ updateShortcutIcon → MethodChannel 'updateShortcut' → ShortcutManagerCompat.updateShortcuts
```
Ghi chú: dialog/snackbar hiện qua `appNavigatorKey` (global) vì có thể app vừa mở do bấm icon (`_waitForContext` chờ Navigator sẵn sàng).

## 1b. Home Screen Widget (App Widget)

**Đẩy trạng thái lên widget (app đang mở hoặc khởi động):**
```
main.dart WidgetService.init()  hoặc  dashboard fetchDevices() thành công
  → WidgetService.refreshAll(): DeviceApi.fetchDevices → phân loại khe (p/c/f)
       → mỗi khe: DeviceApi.fetchStatus → nhãn trạng thái → HomeWidget.saveWidgetData
  → HomeWidget.updateWidget(qualifiedAndroidName: ...SmartHomeWidgetProvider)
    → SmartHomeWidgetProvider.onUpdate đọc SharedPreferences → RemoteViews (ẩn khe {slot}_visible=0)
```

**Bấm nút trên widget (chạy nền, KHÔNG mở app):**
```
Nút widget (PendingIntent = HomeWidgetBackgroundIntent, URI smarthome://action?type&brand&id | smarthome://refresh)
  → HomeWidgetBackgroundReceiver → HomeWidgetBackgroundService (isolate nền)
    → widgetBackgroundCallback(uri) → WidgetService.handleUri
      ├─ action: _performAction (purifierCycle/doorToggle/feederFeed) qua DeviceApi
      └─ refresh: bỏ qua action
    → refreshAll() cập nhật lại widget
```

## 2. Lệnh giọng nói (AI parse)

```
ai_assistant_tab.dart (speech-to-text) → POST /api/ai/parse {text}
  → main.py: firewall device_keywords (không có từ khóa → trả rỗng, bỏ qua AI)
  → câu đơn: parse_command_locally(text, devices)
  → câu phức (và/rồi/với/nhưng) hoặc local rỗng: parse_command_with_ai (OpenRouter)
  → execute_single_action cho mỗi action (asyncio.gather song song)
       connector.turn_on/turn_off/set_mode theo brand
  → trả {ai_understood, execution_results:[{device_name, action, success}]}
```

## 3. Điều khiển trực tiếp từ Dashboard

```
dashboard_tab.dart (nút bật/tắt hoặc mode)
  → DeviceApi (GET /api/test-control/{brand}/{id}?action=  hoặc  /mode?mode=)
  → main.py → device_manager.get_connector(brand) → turn_on/turn_off/set_mode
  → connector gọi cloud của hãng (Tuya/VeSync/Rojeco)
```

## 4. Đọc trạng thái thiết bị

```
dashboard_tab.dart / shortcut_handler.dart → DeviceApi.fetchStatus(brand, id)
  → GET /api/devices/{brand}/{id}/status → connector.get_device_state
  → trả {status: success, data: {status, door_state/position | mode/speed}}
```
