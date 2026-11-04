import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:frontend/core/theme_controller.dart';
import 'package:frontend/theme/app_colors.dart';
import 'package:frontend/theme/app_theme.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('mặc định là TỐI — giao diện cả nhà đang quen', () async {
    ThemeController.mode.value = ThemeMode.light;
    await ThemeController.load();
    expect(ThemeController.mode.value, ThemeMode.dark);
  });

  test('lựa chọn được lưu và đọc lại', () async {
    await ThemeController.set(ThemeMode.light);
    ThemeController.mode.value = ThemeMode.dark;
    await ThemeController.load();
    expect(ThemeController.mode.value, ThemeMode.light);
  });

  test('giá trị lưu hỏng thì về mặc định, không ném lỗi', () async {
    SharedPreferences.setMockInitialValues({'theme_mode_v1': 'tím'});
    await ThemeController.load();
    expect(ThemeController.mode.value, ThemeMode.dark);
  });

  Future<AppPalette> paletteUnder(WidgetTester tester, ThemeMode mode) async {
    late AppPalette seen;
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.lightTheme,
      darkTheme: AppTheme.darkTheme,
      themeMode: mode,
      home: Builder(builder: (context) {
        seen = context.palette;
        return const SizedBox();
      }),
    ));
    // Đổi theme có hiệu ứng chuyển màu: chờ xong mới đọc màu cuối.
    await tester.pumpAndSettle();
    return seen;
  }

  testWidgets('context.palette đổi theo theme đang dùng', (tester) async {
    expect((await paletteUnder(tester, ThemeMode.dark)).background, AppPalette.dark.background);
    expect((await paletteUnder(tester, ThemeMode.light)).background, AppPalette.light.background);
    expect((await paletteUnder(tester, ThemeMode.light)).textMain, AppPalette.light.textMain);
  });

  test('bản tối giữ nguyên màu gốc của app', () {
    expect(AppPalette.dark.background, const Color(0xFF121212));
    expect(AppPalette.dark.primary, const Color(0xFF4DA3FF));
    expect(AppPalette.dark.textMain, const Color(0xFFF8F9FA));
  });
}
