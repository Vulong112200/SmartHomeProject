/// Gom thiết bị theo khu cho dashboard: bộ lọc chip "Tất cả | Phòng khách 1/3 | ...".
///
/// Thuần dữ liệu (không phụ thuộc widget) để test được. Thứ tự khu theo thứ tự
/// backend trả về (`/api/devices` sắp theo zones.sort_order), không theo thứ tự
/// kéo-thả thiết bị của người dùng.
class ZoneGroup {
  final String key;    // zone_id dạng chuỗi, hoặc [unassignedKey]
  final String name;
  final bool shared;   // khu dùng chung cả nhà
  final int total;
  final int on;

  const ZoneGroup({required this.key, required this.name, required this.shared, required this.total, required this.on});
}

const String allZonesKey = 'all';
const String unassignedKey = 'none';

String zoneKeyOf(dynamic device) => device['zone_id'] == null ? unassignedKey : '${device['zone_id']}';

/// Các khu có thiết bị, theo [order] (danh sách key theo thứ tự backend);
/// khu không có trong [order] xếp cuối. "Chưa phân khu" luôn ở cuối cùng.
List<ZoneGroup> zoneGroupsOf(List<dynamic> devices, List<String> order) {
  final byKey = <String, List<dynamic>>{};
  for (final d in devices) {
    byKey.putIfAbsent(zoneKeyOf(d), () => []).add(d);
  }
  int rank(String k) {
    if (k == unassignedKey) return 1 << 30;
    final i = order.indexOf(k);
    return i < 0 ? (1 << 29) : i;
  }

  final keys = byKey.keys.toList()..sort((a, b) => rank(a).compareTo(rank(b)));
  return [
    for (final k in keys)
      ZoneGroup(
        key: k,
        name: k == unassignedKey ? 'Chưa phân khu' : '${byKey[k]!.first['zone_name'] ?? 'Khu $k'}',
        shared: byKey[k]!.first['zone_shared'] == true,
        total: byKey[k]!.length,
        on: byKey[k]!.where((d) => d['is_active'] == true).length,
      ),
  ];
}

/// Thiết bị thuộc khu [key] ([allZonesKey] = tất cả), giữ nguyên thứ tự đầu vào.
List<dynamic> devicesInZone(List<dynamic> devices, String key) =>
    key == allZonesKey ? devices : devices.where((d) => zoneKeyOf(d) == key).toList();
