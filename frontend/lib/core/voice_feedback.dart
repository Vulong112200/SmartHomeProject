import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Trợ lý ĐỌC phản hồi bằng giọng nói ("Đã tắt Máy bơm tăng áp").
///
/// Bật/tắt ở màn Hồ sơ, lưu theo máy. Mặc định BẬT: ra lệnh bằng giọng nói
/// thường là lúc tay đang bận, không nhìn màn hình.
class VoiceFeedback {
  VoiceFeedback._();

  static const _key = 'voice_feedback_v1';
  static final ValueNotifier<bool> enabled = ValueNotifier(true);
  static FlutterTts? _tts;

  static Future<void> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      enabled.value = prefs.getBool(_key) ?? true;
    } catch (_) {}
  }

  static Future<void> setEnabled(bool value) async {
    enabled.value = value;
    if (!value) await _tts?.stop();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_key, value);
  }

  /// Đọc [text] nếu đang bật. Lỗi engine (máy không có giọng tiếng Việt...)
  /// thì im lặng — phản hồi bằng chữ trên màn hình vẫn còn.
  static Future<void> speak(String text) async {
    if (!enabled.value || text.trim().isEmpty) return;
    try {
      final tts = _tts ??= await _create();
      await tts.stop();
      await tts.speak(text);
    } catch (e) {
      debugPrint('TTS lỗi: $e');
    }
  }

  static Future<void> stop() async {
    try {
      await _tts?.stop();
    } catch (_) {}
  }

  static Future<FlutterTts> _create() async {
    final tts = FlutterTts();
    await tts.setLanguage('vi-VN');
    await tts.setSpeechRate(0.5);
    return tts;
  }

  /// Câu tóm tắt kết quả từ `execution_results` của /api/ai/parse.
  /// Thuần dữ liệu để test được.
  static String summarize(List<dynamic> results) {
    if (results.isEmpty) return 'Tôi chưa hiểu lệnh này.';
    final parts = <String>[];
    for (final r in results.whereType<Map>()) {
      final name = '${r['device_name'] ?? ''}'.trim();
      final action = '${r['action'] ?? ''}'.trim();
      if (r['success'] == true) {
        if (action.startsWith('Đã')) {
          parts.add('$name: $action'); // lịch hẹn: "Đã hẹn 16:30 • Bật"
        } else if (action.startsWith('Chế độ')) {
          parts.add('Đã chuyển $name sang ${action.toLowerCase()}');
        } else {
          parts.add('Đã ${action.toLowerCase()} $name'); // Bật/Tắt/Mở/Đóng/Dừng
        }
      } else {
        parts.add('$name: $action');
      }
    }
    return parts.join('. ');
  }
}
