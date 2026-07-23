import 'dart:convert';
import 'package:http/http.dart' as http;

import 'config.dart';
import 'auth_service.dart';

/// Lớp helper dùng CHUNG cho việc gọi API điều khiển & đọc trạng thái thiết bị.
/// Được tái dùng bởi Dashboard (SmartDeviceCard) và Shortcut handler để tránh
/// lặp code.
class DeviceApi {
  static const String baseUrl = AppConfig.baseUrl;
  static const Duration _timeout = AppConfig.apiTimeout;

  /// Lấy trạng thái THẬT của thiết bị từ backend (query phần cứng).
  /// Trả về map data (vd {status, mode, speed} cho máy lọc; {door_state, position}
  /// cho cửa) hoặc null nếu lỗi.
  static Future<Map<String, dynamic>?> fetchStatus(String brand, String deviceId, {bool fresh = false}) async {
    try {
      // fresh=true -> bỏ qua cache backend (dùng sau lệnh điều khiển để bắt kịp
      // trạng thái mới nhất từ cloud, tránh đọc trúng bản cache cũ).
      final q = fresh ? '?fresh=1' : '';
      final res = await http
          .get(Uri.parse('$baseUrl/api/devices/$brand/$deviceId/status$q'),
              headers: AuthService.authHeaders())
          .timeout(_timeout);
      if (res.statusCode == 200) {
        final body = json.decode(utf8.decode(res.bodyBytes));
        if (body['status'] == 'success') {
          return Map<String, dynamic>.from(body['data'] ?? {});
        }
      }
    } catch (_) {
      // Nuốt lỗi: caller tự xử lý null (offline / không hỗ trợ status).
    }
    return null;
  }

  /// Lấy danh sách thiết bị từ backend. Trả về list map hoặc null nếu lỗi.
  static Future<List<Map<String, dynamic>>?> fetchDevices() async {
    try {
      final res = await http
          .get(Uri.parse('$baseUrl/api/devices'), headers: AuthService.authHeaders())
          .timeout(_timeout);
      if (res.statusCode == 200) {
        final body = json.decode(utf8.decode(res.bodyBytes));
        if (body['status'] == 'success') {
          final list = (body['data'] as List?) ?? [];
          return list.map((e) => Map<String, dynamic>.from(e as Map)).toList();
        }
      }
    } catch (_) {
      // Nuốt lỗi: caller tự xử lý null.
    }
    return null;
  }

  /// Kiểm tra response điều khiển thật sự thành công.
  /// Backend trả HTTP 200 kèm {status:"success"|"error"} — lệnh thất bại (thiết
  /// bị không nhận) vẫn là 200 nên phải đọc field `status` trong body.
  static bool _isOk(http.Response res) {
    if (res.statusCode != 200) return false;
    try {
      final body = json.decode(utf8.decode(res.bodyBytes));
      return body['status'] == 'success';
    } catch (_) {
      return false;
    }
  }

  /// Gửi lệnh bật/tắt (action = 'on' | 'off').
  static Future<bool> sendAction(String brand, String deviceId, String action) async {
    try {
      final res = await http
          .get(Uri.parse('$baseUrl/api/test-control/$brand/$deviceId?action=$action'),
              headers: AuthService.authHeaders())
          .timeout(_timeout);
      return _isOk(res);
    } catch (_) {
      return false;
    }
  }

  /// Gửi lệnh đổi chế độ (mode = '1'|'2'|'3'|'auto'|'sleep' cho lọc; 'open'|'close'|'stop'
  /// cho cửa; số phần cho máy cho ăn).
  static Future<bool> sendMode(String brand, String deviceId, String mode) async {
    try {
      final res = await http
          .get(Uri.parse('$baseUrl/api/test-control/$brand/$deviceId/mode?mode=$mode'),
              headers: AuthService.authHeaders())
          .timeout(_timeout);
      return _isOk(res);
    } catch (_) {
      return false;
    }
  }
}

/// Một bước trong vòng xoay chế độ của máy lọc không khí.
class PurifierStep {
  final String key; // định danh trạng thái (dùng để suy icon)
  final String label; // hiển thị cho người dùng
  final String kind; // 'off' | 'on' | 'mode'
  final String? mode; // mode gửi khi kind == 'mode'
  const PurifierStep(this.key, this.label, this.kind, [this.mode]);
}

/// Logic vòng xoay chế độ máy lọc (dùng chung cho card & shortcut).
/// Thứ tự: Tắt → Bật → Lọc thấp → Lọc TB → Lọc cao → Auto → Ngủ → (quay lại Tắt).
class PurifierCycle {
  static const List<PurifierStep> steps = [
    PurifierStep('off', 'Tắt', 'off'),
    PurifierStep('on', 'Bật (Mở)', 'on'),
    PurifierStep('low', 'Lọc Thấp', 'mode', '1'),
    PurifierStep('med', 'Lọc TB', 'mode', '2'),
    PurifierStep('high', 'Lọc Cao', 'mode', '3'),
    PurifierStep('auto', 'Lọc Auto', 'mode', 'auto'),
    PurifierStep('sleep', 'Lọc Ngủ', 'mode', 'sleep'),
  ];

  /// Suy ra chỉ số bước hiện tại từ trạng thái backend trả về.
  /// status: 'ON'/'OFF'; mode: 'auto'/'sleep'/'manual'; speed/fan_level: 1..3.
  static int indexFromStatus(Map<String, dynamic>? status) {
    if (status == null) return 0;
    final on = '${status['status']}'.toUpperCase() == 'ON';
    if (!on) return 0; // Tắt
    final mode = '${status['mode']}'.toLowerCase();
    if (mode == 'auto') return 5;
    if (mode == 'sleep') return 6;
    final speed = '${status['speed'] ?? status['fan_level']}';
    if (speed == '1') return 2;
    if (speed == '2') return 3;
    if (speed == '3') return 4;
    return 1; // đang bật nhưng chưa rõ tốc độ
  }

  static PurifierStep next(int currentIndex) {
    final nextIndex = (currentIndex + 1) % steps.length;
    return steps[nextIndex];
  }

  /// Thực thi 1 bước lên backend.
  static Future<bool> apply(String brand, String deviceId, PurifierStep step) {
    switch (step.kind) {
      case 'off':
        return DeviceApi.sendAction(brand, deviceId, 'off');
      case 'on':
        return DeviceApi.sendAction(brand, deviceId, 'on');
      case 'mode':
        return DeviceApi.sendMode(brand, deviceId, step.mode!);
      default:
        return Future.value(false);
    }
  }
}
