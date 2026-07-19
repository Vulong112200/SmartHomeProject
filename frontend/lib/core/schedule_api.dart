import 'dart:convert';
import 'package:http/http.dart' as http;

import 'config.dart';

/// Một lịch hẹn giờ (khớp bảng `schedules` phía backend).
class Schedule {
  final int id;
  final String name;
  final String brand;
  final String deviceId;
  final String actionType;   // on | off | mode
  final String? actionValue; // 1/2/3/auto/sleep/open/close/stop; null với on/off
  final String time;         // "HH:MM" giờ VN
  final String days;         // CSV 0-6 (0=Thứ2); rỗng = mỗi ngày
  final bool enabled;

  const Schedule({
    required this.id,
    required this.name,
    required this.brand,
    required this.deviceId,
    required this.actionType,
    required this.actionValue,
    required this.time,
    required this.days,
    required this.enabled,
  });

  factory Schedule.fromJson(Map<String, dynamic> j) => Schedule(
        id: j['id'] as int,
        name: '${j['name'] ?? ''}',
        brand: '${j['brand']}',
        deviceId: '${j['device_id']}',
        actionType: '${j['action_type']}',
        actionValue: j['action_value']?.toString(),
        time: '${j['time']}',
        days: '${j['days'] ?? ''}',
        enabled: j['enabled'] == true,
      );
}

/// Helper gọi API Hẹn giờ (song song với DeviceApi).
class ScheduleApi {
  static const String _base = '${AppConfig.baseUrl}/api/schedules';

  static Future<List<Schedule>?> fetchSchedules() async {
    try {
      final res = await http.get(Uri.parse(_base)).timeout(AppConfig.apiTimeout);
      if (res.statusCode == 200) {
        final body = json.decode(utf8.decode(res.bodyBytes));
        if (body['status'] == 'success') {
          final list = (body['data'] as List?) ?? [];
          return list
              .map((e) => Schedule.fromJson(Map<String, dynamic>.from(e as Map)))
              .toList();
        }
      }
    } catch (_) {
      // Caller xử lý null (offline).
    }
    return null;
  }

  /// Tạo lịch mới. Trả về thông báo lỗi (tiếng Việt) hoặc null nếu thành công.
  static Future<String?> createSchedule({
    required String name,
    required String brand,
    required String deviceId,
    required String actionType,
    String? actionValue,
    required String time,
    required String days,
    bool enabled = true,
  }) async {
    return _send(
      () => http.post(
        Uri.parse(_base),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'name': name,
          'brand': brand,
          'device_id': deviceId,
          'action_type': actionType,
          'action_value': actionValue,
          'time': time,
          'days': days,
          'enabled': enabled,
        }),
      ),
    );
  }

  /// Sửa lịch (chỉ gửi các field cần đổi). Trả lỗi hoặc null nếu thành công.
  static Future<String?> updateSchedule(int id, Map<String, dynamic> fields) async {
    return _send(
      () => http.patch(
        Uri.parse('$_base/$id'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode(fields),
      ),
    );
  }

  static Future<String?> deleteSchedule(int id) async {
    return _send(() => http.delete(Uri.parse('$_base/$id')));
  }

  /// Chạy NGAY hành động của lịch (test). Trả lỗi hoặc null nếu thành công.
  static Future<String?> runNow(int id) async {
    return _send(() => http.post(Uri.parse('$_base/$id/run')),
        timeout: const Duration(seconds: 20)); // lệnh IoT thật có thể chậm hơn API thường
  }

  /// Gửi request rồi đọc {status, message}: null nếu success, message nếu lỗi.
  static Future<String?> _send(Future<http.Response> Function() request,
      {Duration? timeout}) async {
    try {
      final res = await request().timeout(timeout ?? AppConfig.apiTimeout);
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body['status'] == 'success') return null;
      return '${body['message'] ?? 'Lỗi máy chủ (HTTP ${res.statusCode})'}';
    } catch (_) {
      return 'Mất kết nối máy chủ. Thử lại sau.';
    }
  }
}
