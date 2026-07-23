import 'package:shared_preferences/shared_preferences.dart';

/// Lưu & áp thứ tự hiển thị thiết bị trên dashboard (CỤC BỘ trên máy).
///
/// Thứ tự chỉ là tuỳ biến hiển thị phía client — backend `DeviceModel` không có
/// cột thứ tự. Lưu danh sách `id` theo đúng thứ tự người dùng kéo-thả vào
/// SharedPreferences; khi tải lại thì sắp `devices` theo danh sách này.
class DeviceOrder {
  static const String _key = 'device_order_v1';

  /// Đọc thứ tự đã lưu (danh sách id). Rỗng nếu chưa từng sắp xếp.
  static Future<List<String>> load() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getStringList(_key) ?? const [];
  }

  /// Lưu thứ tự hiện tại (danh sách id theo đúng thứ tự hiển thị).
  static Future<void> save(List<String> ids) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_key, ids);
  }

  /// Sắp `devices` theo `order` đã lưu. Thiết bị CHƯA có trong `order` (mới thêm
  /// sau lần sắp xếp gần nhất) giữ nguyên thứ tự backend và được đẩy xuống cuối.
  /// Trả về danh sách mới (không sửa danh sách gốc).
  static List<dynamic> apply(List<dynamic> devices, List<String> order) {
    if (order.isEmpty) return List<dynamic>.from(devices);
    final rank = <String, int>{for (var i = 0; i < order.length; i++) order[i]: i};
    final known = <dynamic>[];
    final unknown = <dynamic>[];
    for (final d in devices) {
      final id = '${d['id']}';
      (rank.containsKey(id) ? known : unknown).add(d);
    }
    known.sort((a, b) => rank['${a['id']}']!.compareTo(rank['${b['id']}']!));
    return [...known, ...unknown];
  }
}
