/// Phân loại thiết bị — nơi DUY NHẤT chứa logic phân loại.
/// Ưu tiên `category` chủ nhà đặt ở backend (cột devices.category); NULL thì
/// suy từ tên tiếng Việt như cũ. Trước đây logic này bị lặp ở dashboard_tab
/// và widget_service.
/// powerSwitch = công tắc bật/tắt đơn (vd. máy bơm tăng áp qua công tắc Tuya).
enum DeviceType { airPurifier, feeder, curtain, powerSwitch, unknown }

/// Giá trị `category` phía backend (models/device.py DEVICE_CATEGORIES).
/// Thêm loại mới thì phải sửa CẢ HAI nơi.
const Map<String, DeviceType> deviceCategories = {
  'purifier': DeviceType.airPurifier,
  'curtain': DeviceType.curtain,
  'feeder': DeviceType.feeder,
  'switch': DeviceType.powerSwitch,
};

/// Nhãn tiếng Việt cho từng category (dùng ở màn quản trị).
const Map<String, String> deviceCategoryLabels = {
  'purifier': 'Máy lọc không khí',
  'curtain': 'Cửa cuốn / rèm',
  'feeder': 'Máy cho ăn',
  'switch': 'Công tắc (máy bơm...)',
};

DeviceType deviceTypeOf(String name, {String? category}) {
  final byCategory = deviceCategories[category];
  if (byCategory != null) return byCategory;

  final n = name.toLowerCase();
  // Công tắc kiểm TRƯỚC máy cho ăn: "tăng áp" chứa chuỗi "ăn".
  if (n.contains('bơm') || n.contains('tăng áp') || n.contains('công tắc')) {
    return DeviceType.powerSwitch;
  }
  if (n.contains('lọc')) return DeviceType.airPurifier;
  if (n.contains('cửa')) return DeviceType.curtain;
  if (n.contains('mèo') || n.contains('ăn')) return DeviceType.feeder;
  return DeviceType.unknown;
}

/// Một hành động chọn được cho thiết bị (nhãn + giá trị gửi backend).
/// Dùng chung cho form lịch hẹn và form kịch bản. Khớp backend
/// services/device_actions.py (cửa chỉ mở/đóng/dừng, máy cho ăn chỉ nhả hạt).
class DeviceActionOption {
  final String label;
  final String actionType;   // on | off | mode
  final String? actionValue; // đi kèm khi actionType == mode
  const DeviceActionOption(this.label, this.actionType, [this.actionValue]);

  String get key => '$actionType:${actionValue ?? ''}';
}

/// Danh sách hành động khả dụng theo loại thiết bị.
List<DeviceActionOption> deviceActionOptions(DeviceType type) {
  switch (type) {
    case DeviceType.airPurifier:
      return const [
        DeviceActionOption('Bật', 'on'),
        DeviceActionOption('Tắt', 'off'),
        DeviceActionOption('Lọc Thấp', 'mode', '1'),
        DeviceActionOption('Lọc TB', 'mode', '2'),
        DeviceActionOption('Lọc Cao', 'mode', '3'),
        DeviceActionOption('Lọc Auto', 'mode', 'auto'),
        DeviceActionOption('Lọc Ngủ', 'mode', 'sleep'),
      ];
    case DeviceType.curtain:
      return const [
        DeviceActionOption('Mở cửa', 'mode', 'open'),
        DeviceActionOption('Đóng cửa', 'mode', 'close'),
        DeviceActionOption('Dừng cửa', 'mode', 'stop'),
      ];
    case DeviceType.feeder:
      return const [
        DeviceActionOption('Nhả 1 phần', 'mode', '1'),
        DeviceActionOption('Nhả 2 phần', 'mode', '2'),
        DeviceActionOption('Nhả 3 phần', 'mode', '3'),
      ];
    case DeviceType.powerSwitch:
    case DeviceType.unknown:
      return const [
        DeviceActionOption('Bật', 'on'),
        DeviceActionOption('Tắt', 'off'),
      ];
  }
}

/// Nhãn tiếng Việt cho 1 hành động (dùng cho cả hành động bắt đầu lẫn kết thúc).
String deviceActionLabel(String actionType, String? actionValue, DeviceType type) {
  for (final opt in deviceActionOptions(type)) {
    if (opt.actionType == actionType && opt.actionValue == actionValue) {
      return opt.label;
    }
  }
  // Fallback khi loại thiết bị không xác định được từ tên.
  if (actionType == 'on') return 'Bật';
  if (actionType == 'off') return 'Tắt';
  return 'Chế độ ${actionValue ?? '?'}';
}
