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
