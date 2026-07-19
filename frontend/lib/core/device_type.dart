/// Suy loại thiết bị từ tên (tiếng Việt) — nơi DUY NHẤT chứa logic phân loại.
/// Backend không có cột type/category nên client suy từ tên; trước đây logic
/// này bị lặp ở dashboard_tab và widget_service.
enum DeviceType { airPurifier, feeder, curtain, unknown }

DeviceType deviceTypeOf(String name) {
  final n = name.toLowerCase();
  if (n.contains('lọc')) return DeviceType.airPurifier;
  if (n.contains('cửa')) return DeviceType.curtain;
  if (n.contains('mèo') || n.contains('ăn')) return DeviceType.feeder;
  return DeviceType.unknown;
}
