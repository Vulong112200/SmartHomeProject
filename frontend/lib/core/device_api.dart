import 'dart:convert';
import 'package:http/http.dart' as http;

/// Lớp helper dùng CHUNG cho việc gọi API điều khiển & đọc trạng thái thiết bị.
/// Được tái dùng bởi Dashboard (SmartDeviceCard) và Shortcut handler để tránh
/// lặp code.
class DeviceApi {
  static const String baseUrl = 'https://vuhp-smarthome.onrender.com';
  static const Duration _timeout = Duration(seconds: 6);

  /// Lấy trạng thái THẬT của thiết bị từ backend (query phần cứng).
  /// Trả về map data (vd {status, mode, speed} cho máy lọc; {door_state, position}
  /// cho cửa) hoặc null nếu lỗi.
  static Future<Map<String, dynamic>?> fetchStatus(String brand, String deviceId) async {
    try {
      final res = await http
          .get(Uri.parse('$baseUrl/api/devices/$brand/$deviceId/status'))
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

  /// Gửi lệnh bật/tắt (action = 'on' | 'off').
  static Future<bool> sendAction(String brand, String deviceId, String action) async {
    try {
      final res = await http
          .get(Uri.parse('$baseUrl/api/test-control/$brand/$deviceId?action=$action'))
          .timeout(_timeout);
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Gửi lệnh đổi chế độ (mode = '1'|'2'|'3'|'auto'|'sleep' cho lọc; 'open'|'close'|'stop'
  /// cho cửa; số phần cho máy cho ăn).
  static Future<bool> sendMode(String brand, String deviceId, String mode) async {
    try {
      final res = await http
          .get(Uri.parse('$baseUrl/api/test-control/$brand/$deviceId/mode?mode=$mode'))
          .timeout(_timeout);
      return res.statusCode == 200;
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
