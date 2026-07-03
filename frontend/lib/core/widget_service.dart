import 'package:home_widget/home_widget.dart';

import 'device_api.dart';
import 'shortcut_service.dart';

/// Tên đầy đủ của AppWidgetProvider phía Android (khớp package + class).
const String _androidWidgetProvider = 'com.example.frontend.SmartHomeWidgetProvider';

/// Callback chạy NỀN khi bấm nút trên widget (không mở app).
/// Bắt buộc là hàm top-level + @pragma('vm:entry-point') để isolate nền gọi được.
@pragma('vm:entry-point')
Future<void> widgetBackgroundCallback(Uri? uri) async {
  if (uri == null) return;
  await WidgetService.handleUri(uri);
}

/// Cầu nối giữa app và Home Screen Widget:
/// - Đẩy trạng thái sống của thiết bị lên widget.
/// - Xử lý nút bấm trên widget (chạy nền) rồi cập nhật lại.
class WidgetService {
  /// Gọi 1 lần trong main(): đăng ký callback nền + nạp dữ liệu lần đầu.
  static Future<void> init() async {
    await HomeWidget.registerInteractivityCallback(widgetBackgroundCallback);
    await refreshAll();
  }

  // ---- Phân loại thiết bị theo tên (khớp logic dashboard) ----
  static bool _isPurifier(String n) => n.toLowerCase().contains('lọc');
  static bool _isFeeder(String n) =>
      n.toLowerCase().contains('mèo') || n.toLowerCase().contains('ăn');
  static bool _isCurtain(String n) => n.toLowerCase().contains('cửa');

  /// Lấy toàn bộ thiết bị + trạng thái, đẩy lên widget rồi yêu cầu vẽ lại.
  static Future<void> refreshAll() async {
    final devices = await DeviceApi.fetchDevices();
    if (devices == null) {
      // Không lấy được: vẫn yêu cầu vẽ lại để giữ dữ liệu cũ.
      await _update();
      return;
    }

    await _clearSlots();
    for (final d in devices) {
      final name = '${d['name']}';
      final brand = '${d['brand']}'.toLowerCase();
      final id = '${d['id']}';
      if (_isPurifier(name)) {
        await _fillPurifier(brand, id, name);
      } else if (_isCurtain(name)) {
        await _fillCurtain(brand, id, name);
      } else if (_isFeeder(name)) {
        await _fillFeeder(brand, id, name);
      }
    }
    await _update();
  }

  /// Xử lý URI từ nút widget: smarthome://refresh hoặc smarthome://action?type&brand&id
  static Future<void> handleUri(Uri uri) async {
    if (uri.host == 'refresh') {
      await refreshAll();
      return;
    }
    final type = uri.queryParameters['type'] ?? '';
    final brand = uri.queryParameters['brand'] ?? '';
    final id = uri.queryParameters['id'] ?? '';
    if (type.isNotEmpty && brand.isNotEmpty && id.isNotEmpty) {
      await _performAction(type, brand, id);
    }
    await refreshAll();
  }

  static Future<void> _performAction(String type, String brand, String id) async {
    switch (type) {
      case ShortcutType.purifierCycle:
        final s = await DeviceApi.fetchStatus(brand, id);
        final step = PurifierCycle.next(PurifierCycle.indexFromStatus(s));
        await PurifierCycle.apply(brand, id, step);
        break;
      case ShortcutType.doorToggle:
        final s = await DeviceApi.fetchStatus(brand, id);
        final ds = '${s?['door_state']}'.toLowerCase();
        final closed = ds == 'closed' || ds == 'closing';
        await DeviceApi.sendMode(brand, id, closed ? 'open' : 'close');
        break;
      case ShortcutType.feederFeed:
        await DeviceApi.sendMode(brand, id, '1');
        break;
    }
  }

  // ---- Điền dữ liệu từng khe ----
  static Future<void> _fillPurifier(String brand, String id, String name) async {
    final s = await DeviceApi.fetchStatus(brand, id);
    final idx = PurifierCycle.indexFromStatus(s);
    final on = s != null && '${s['status']}'.toUpperCase() == 'ON';
    final label = s == null
        ? 'Không rõ'
        : (on ? 'Đang chạy: ${PurifierCycle.steps[idx].label}' : 'Đã tắt');
    await _saveSlot('p', name, label, ShortcutType.purifierCycle, brand, id);
  }

  static Future<void> _fillCurtain(String brand, String id, String name) async {
    final s = await DeviceApi.fetchStatus(brand, id);
    final ds = '${s?['door_state'] ?? 'unknown'}'.toLowerCase();
    const map = {
      'open': 'Đang mở',
      'opening': 'Đang mở...',
      'closed': 'Đã đóng',
      'closing': 'Đang đóng...',
      'stopped': 'Đã dừng',
      'partial': 'Mở một phần',
    };
    final label = s == null ? 'Không rõ' : (map[ds] ?? 'Không rõ');
    await _saveSlot('c', name, label, ShortcutType.doorToggle, brand, id);
  }

  static Future<void> _fillFeeder(String brand, String id, String name) async {
    final s = await DeviceApi.fetchStatus(brand, id);
    final online = s != null && '${s['status']}'.toUpperCase() != 'OFFLINE';
    final label = s == null ? 'Không rõ' : (online ? 'Sẵn sàng' : 'Mất kết nối');
    await _saveSlot('f', name, label, ShortcutType.feederFeed, brand, id);
  }

  static Future<void> _saveSlot(
    String slot,
    String name,
    String status,
    String type,
    String brand,
    String id,
  ) async {
    await HomeWidget.saveWidgetData<String>('${slot}_visible', '1');
    await HomeWidget.saveWidgetData<String>('${slot}_name', name);
    await HomeWidget.saveWidgetData<String>('${slot}_status', status);
    await HomeWidget.saveWidgetData<String>('${slot}_type', type);
    await HomeWidget.saveWidgetData<String>('${slot}_brand', brand);
    await HomeWidget.saveWidgetData<String>('${slot}_id', id);
  }

  static Future<void> _clearSlots() async {
    for (final slot in ['p', 'c', 'f']) {
      await HomeWidget.saveWidgetData<String>('${slot}_visible', '0');
    }
  }

  static Future<void> _update() async {
    await HomeWidget.updateWidget(qualifiedAndroidName: _androidWidgetProvider);
  }
}
