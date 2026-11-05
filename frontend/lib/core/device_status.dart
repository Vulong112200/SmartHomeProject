import 'device_api.dart';
import 'device_type.dart';

/// Diễn giải trạng thái THẬT (`GET /api/devices/{brand}/{id}/status`) thành
/// thứ giao diện cần: trạng thái hiển thị, nhãn tiếng Việt, hành động đang
/// hoạt động (để tô sáng nút), và "lệnh vừa gửi đã được xác nhận chưa".
///
/// Thuần dữ liệu — dùng cho Sơ đồ mặt bằng; nhãn khớp thẻ ở Dashboard.
enum DeviceVisualState {
  /// Chưa đọc được trạng thái (đang tải / máy chủ không trả lời).
  unknown,

  /// Thiết bị báo mất kết nối với cloud của hãng.
  offline,

  /// Đang bật / cửa đang mở.
  active,

  /// Đang tắt / cửa đã đóng / máy cho ăn sẵn sàng.
  idle,

  /// Đang chuyển động: cửa đang mở/đóng, máy cho ăn đang nhả hạt.
  moving,
}

class DeviceStatusView {
  final DeviceVisualState state;
  final String label;
  const DeviceStatusView(this.state, this.label);
}

bool _isOffline(Map<String, dynamic> s) => '${s['status']}'.toLowerCase() == 'offline';
bool _isOn(Map<String, dynamic> s) => '${s['status']}'.toUpperCase() == 'ON';

DeviceStatusView describeDeviceStatus(DeviceType type, Map<String, dynamic>? s) {
  if (s == null) return const DeviceStatusView(DeviceVisualState.unknown, 'Chưa rõ trạng thái');
  if (_isOffline(s)) return const DeviceStatusView(DeviceVisualState.offline, 'Mất kết nối');

  switch (type) {
    case DeviceType.airPurifier:
      if (!_isOn(s)) return const DeviceStatusView(DeviceVisualState.idle, 'Đã tắt');
      final step = PurifierCycle.steps[PurifierCycle.indexFromStatus(s)];
      return DeviceStatusView(DeviceVisualState.active, 'Đang chạy: ${step.label}');

    case DeviceType.curtain:
      switch ('${s['door_state'] ?? ''}'.toLowerCase()) {
        case 'open':
          return const DeviceStatusView(DeviceVisualState.active, 'Đang mở');
        case 'partial':
          return const DeviceStatusView(DeviceVisualState.active, 'Mở một phần');
        case 'stopped':
          return const DeviceStatusView(DeviceVisualState.active, 'Đã dừng');
        case 'opening':
          return const DeviceStatusView(DeviceVisualState.moving, 'Đang mở...');
        case 'closing':
          return const DeviceStatusView(DeviceVisualState.moving, 'Đang đóng...');
        case 'closed':
          return const DeviceStatusView(DeviceVisualState.idle, 'Đã đóng');
        default:
          return const DeviceStatusView(DeviceVisualState.unknown, 'Chưa rõ trạng thái');
      }

    case DeviceType.feeder:
      if (!_isOn(s)) return const DeviceStatusView(DeviceVisualState.offline, 'Mất kết nối');
      if (s['feed_state'] == 'feeding') {
        return const DeviceStatusView(DeviceVisualState.moving, 'Đang nhả hạt...');
      }
      final last = s['last_feed'];
      return DeviceStatusView(
        DeviceVisualState.idle,
        last is int && last > 0 ? 'Sẵn sàng • lần trước $last phần' : 'Sẵn sàng',
      );

    case DeviceType.powerSwitch:
    case DeviceType.unknown:
      final st = '${s['status']}'.toUpperCase();
      if (st == 'ON') return const DeviceStatusView(DeviceVisualState.active, 'Đang chạy');
      if (st == 'OFF') return const DeviceStatusView(DeviceVisualState.idle, 'Đã tắt');
      return const DeviceStatusView(DeviceVisualState.offline, 'Mất kết nối');
  }
}

/// `DeviceActionOption.key` của hành động ĐANG có hiệu lực theo trạng thái
/// thật (để tô sáng nút). null = không xác định / máy cho ăn (không có "đang").
String? currentActionKey(DeviceType type, Map<String, dynamic>? s) {
  if (s == null || _isOffline(s)) return null;
  switch (type) {
    case DeviceType.airPurifier:
      if (!_isOn(s)) return 'off:';
      final step = PurifierCycle.steps[PurifierCycle.indexFromStatus(s)];
      return step.mode == null ? 'on:' : 'mode:${step.mode}';
    case DeviceType.curtain:
      return const {
        'open': 'mode:open',
        'opening': 'mode:open',
        'closed': 'mode:close',
        'closing': 'mode:close',
        'stopped': 'mode:stop',
      }['${s['door_state'] ?? ''}'.toLowerCase()];
    case DeviceType.feeder:
      return null;
    case DeviceType.powerSwitch:
    case DeviceType.unknown:
      final st = '${s['status']}'.toUpperCase();
      return st == 'ON' ? 'on:' : (st == 'OFF' ? 'off:' : null);
  }
}

/// Trạng thái thật `s` đã phản ánh lệnh `option` vừa gửi chưa.
/// Máy lọc "Bật" khớp mọi chế độ đang chạy; máy cho ăn chỉ cần đọc lại được.
bool statusConfirms(DeviceType type, DeviceActionOption option, Map<String, dynamic>? s) {
  if (s == null || _isOffline(s)) return false;
  if (type == DeviceType.feeder) return true;
  if (type == DeviceType.airPurifier && option.actionType == 'on') return _isOn(s);
  return currentActionKey(type, s) == option.key;
}

/// Loại cần poll trạng thái định kỳ (khớp Dashboard: máy cho ăn KHÔNG poll —
/// tiết kiệm quota Tuya, chỉ đọc khi hiện + sau lệnh).
bool needsPolling(DeviceType type) =>
    type == DeviceType.airPurifier || type == DeviceType.curtain || type == DeviceType.powerSwitch;
