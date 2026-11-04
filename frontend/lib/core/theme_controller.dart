import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Chế độ giao diện Sáng / Tối / Theo hệ thống, lưu theo máy (SharedPreferences).
///
/// Mặc định TỐI — đúng giao diện cả nhà đang quen; ai muốn đổi thì vào Hồ sơ.
class ThemeController {
  ThemeController._();

  static const _key = 'theme_mode_v1';

  static final ValueNotifier<ThemeMode> mode = ValueNotifier(ThemeMode.dark);

  static const Map<ThemeMode, String> labels = {
    ThemeMode.system: 'Theo hệ thống',
    ThemeMode.light: 'Sáng',
    ThemeMode.dark: 'Tối',
  };

  /// Đọc lựa chọn đã lưu. Gọi 1 lần trước runApp để không nháy theme sai.
  static Future<void> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      mode.value = _parse(prefs.getString(_key));
    } catch (_) {
      // Không đọc được prefs: giữ mặc định.
    }
  }

  static Future<void> set(ThemeMode value) async {
    mode.value = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, value.name);
  }

  static ThemeMode _parse(String? raw) => ThemeMode.values.firstWhere(
        (m) => m.name == raw,
        orElse: () => ThemeMode.dark,
      );
}
