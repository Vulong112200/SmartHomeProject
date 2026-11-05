import 'dart:async';
import 'dart:math' as math;

import 'package:shared_preferences/shared_preferences.dart';

/// Thứ tự hiển thị thiết bị trên Dashboard (kéo-thả).
///
/// Có 2 chế độ:
/// - **Đồng bộ theo tài khoản** (có đăng nhập): thứ tự nằm ở server
///   (`members.sort_order`, đọc qua `GET /api/me`, ghi qua `PATCH /api/me`) —
///   xem [DeviceOrderSync].
/// - **Cục bộ** (bản build chưa bật đăng nhập): lưu SharedPreferences
///   `device_order_v1` như trước. Khi chuyển sang chế độ đồng bộ, danh sách cục
///   bộ này được đẩy lên server MỘT LẦN nếu tài khoản chưa có thứ tự nào, để
///   người dùng không mất thứ tự đang có.
class DeviceOrder {
  static const String legacyKey = 'device_order_v1';

  /// Đọc thứ tự cục bộ (danh sách id). Rỗng nếu chưa từng sắp xếp.
  static Future<List<String>> load() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getStringList(legacyKey) ?? const [];
  }

  /// Lưu thứ tự cục bộ (chỉ dùng ở chế độ cục bộ).
  static Future<void> save(List<String> ids) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(legacyKey, ids);
  }

  /// Xóa thứ tự cục bộ cũ sau khi đã chuyển sang đồng bộ theo tài khoản —
  /// tránh tài khoản khác đăng nhập trên cùng máy bị "thừa kế" thứ tự này.
  static Future<void> clearLegacy() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(legacyKey);
  }

  /// Sắp `devices` theo `order`. Thiết bị CHƯA có trong `order` (mới thêm sau
  /// lần sắp xếp gần nhất) giữ nguyên thứ tự backend và được đẩy xuống cuối.
  /// Id trong `order` không còn trong `devices` (đã xóa / mất quyền) tự bị bỏ
  /// qua. Trả về danh sách mới (không sửa danh sách gốc).
  static List<dynamic> apply(List<dynamic> devices, List<String> order) {
    if (order.isEmpty) return List<dynamic>.from(devices);
    final rank = <String, int>{};
    for (var i = 0; i < order.length; i++) {
      rank.putIfAbsent(order[i], () => i);
    }
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

/// Gửi thứ tự lên server. `true` = đã lưu.
typedef DeviceOrderSender = Future<bool> Function(List<String> ids);

/// Đồng bộ thứ tự thiết bị lên tài khoản, có debounce + thử lại.
///
/// - [schedule]: gọi sau mỗi lần kéo-thả. Hẹn gửi sau [debounce]; kéo tiếp
///   trong lúc chờ thì hủy hẹn cũ, chỉ gửi danh sách MỚI NHẤT.
/// - Bản chưa gửi được ghi xuống SharedPreferences ngay ⇒ app bị tắt trước khi
///   gửi thì lần mở sau [restore] nạp lại và gửi tiếp (không mất thao tác).
/// - Gửi lỗi (mất mạng, server ngủ) ⇒ giữ bản chờ, thử lại sau [retryDelays]
///   (giãn dần, dừng ở mức cuối) cho tới khi thành công hoặc [dispose].
/// - Không bao giờ có 2 request song song.
class DeviceOrderSync {
  final String userId;
  final DeviceOrderSender send;
  final Duration debounce;
  final List<Duration> retryDelays;

  DeviceOrderSync({
    required this.userId,
    required this.send,
    this.debounce = const Duration(seconds: 2),
    this.retryDelays = const [Duration(seconds: 5), Duration(seconds: 15), Duration(seconds: 60)],
  });

  List<String>? _pending;
  Timer? _timer;
  bool _sending = false;
  bool _disposed = false;
  int _failures = 0;

  String get _pendingKey => 'device_order_pending_v2:$userId';

  /// Danh sách đang chờ gửi (null = không có gì chờ).
  List<String>? get pending => _pending;
  bool get hasPending => _pending != null;

  /// Lần gửi gần nhất bị lỗi và đang chờ thử lại.
  bool get isRetrying => _pending != null && _failures > 0;

  /// Nạp bản chưa gửi được từ phiên trước (nếu có).
  Future<void> restore() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getStringList(_pendingKey);
    if (saved != null && _pending == null) _pending = saved;
  }

  /// Hẹn gửi [ids] sau [debounce] (hủy lần hẹn trước).
  void schedule(List<String> ids) {
    if (_disposed) return;
    _pending = List<String>.unmodifiable(ids);
    _failures = 0;
    _persist(_pending!);
    _arm(debounce);
  }

  /// Gửi NGAY bản đang chờ (bỏ qua debounce). Dùng khi app vào nền / rời tab /
  /// màn hình bị hủy, hoặc khi mạng vừa có lại.
  Future<void> flush() async {
    _timer?.cancel();
    final ids = _pending;
    if (ids == null || _sending) return; // đang gửi: xong sẽ tự xử lý bản mới hơn
    _sending = true;
    var ok = false;
    try {
      ok = await send(ids);
    } catch (_) {
      ok = false;
    }
    _sending = false;

    if (!identical(_pending, ids)) {
      // Người dùng kéo tiếp trong lúc đang gửi: schedule() đã hẹn giờ cho bản
      // mới; nếu đã bị dispose thì bản mới nằm trong SharedPreferences.
      return;
    }
    if (ok) {
      _pending = null;
      _failures = 0;
      await _clearPersisted();
    } else {
      final delay = retryDelays[math.min(_failures, retryDelays.length - 1)];
      _failures++;
      _arm(delay);
    }
  }

  /// Dừng hẹn giờ / thử lại. Bản chưa gửi vẫn nằm trong SharedPreferences.
  void dispose() {
    _disposed = true;
    _timer?.cancel();
  }

  void _arm(Duration delay) {
    _timer?.cancel();
    if (_disposed) return;
    _timer = Timer(delay, flush);
  }

  Future<void> _persist(List<String> ids) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(_pendingKey, ids);
    } catch (_) {
      // Không ghi được đĩa: vẫn còn bản trong RAM để gửi trong phiên này.
    }
  }

  Future<void> _clearPersisted() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      // Chỉ xóa khi không có bản mới hơn được hẹn trong lúc chờ đĩa.
      if (_pending == null) await prefs.remove(_pendingKey);
    } catch (_) {}
  }
}
