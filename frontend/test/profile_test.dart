import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:frontend/core/auth_service.dart';
import 'package:frontend/core/avatar.dart';
import 'package:frontend/core/theme_controller.dart';
import 'package:frontend/screens/profile_screen.dart';
import 'package:frontend/theme/app_theme.dart';

HouseholdProfile _p({String name = 'Hà Phi Vũ', String? color, String id = 'u-1', String email = 'vu@x.test'}) =>
    HouseholdProfile(
      userId: id,
      email: email,
      displayName: name,
      avatarColor: color,
      role: 'kid',
      status: 'active',
      canAdmin: false,
      canSchedule: true,
      zoneIds: const [1],
      zones: const [
        {'id': 1, 'name': 'Phòng ngủ'}
      ],
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('chữ cái đầu lấy từ chữ đầu và chữ cuối của tên', () {
    expect(initialsOf(_p()), 'HV');
    expect(initialsOf(_p(name: 'na')), 'N');
    expect(initialsOf(_p(name: '', email: 'bo.me@x.test')), 'B');
    expect(initialsOf(_p(name: '', email: '')), isNull);
  });

  test('màu tự động ổn định theo người, màu tự chọn thắng', () {
    expect(avatarColorOf(_p(id: 'abc')), avatarColorOf(_p(id: 'abc', name: 'Tên khác')));
    expect(avatarColorOf(_p(color: '#112233')), const Color(0xFF112233));
    // Giá trị lưu hỏng -> quay về màu tự động, không crash.
    expect(avatarColorOf(_p(color: 'đỏ', id: 'abc')), avatarColorOf(_p(id: 'abc')));
  });

  test('fromJson đọc avatar_color và zone_ids kiểu số bất kỳ', () {
    final p = HouseholdProfile.fromJson({
      'user_id': 'u', 'email': 'e@x', 'display_name': 'E', 'avatar_color': '#AABBCC',
      'role': 'kid', 'status': 'active', 'zone_ids': [1, 2.0],
    });
    expect(p.avatarColor, '#AABBCC');
    expect(p.zoneIds, [1, 2]);
  });

  test('copyWith đổi tên/màu, giữ nguyên vai', () {
    final p = _p(color: '#112233').copyWith(displayName: 'Mới', clearAvatarColor: true);
    expect((p.displayName, p.avatarColor, p.role), ('Mới', null, 'kid'));
  });

  testWidgets('màn Hồ sơ hiện tên, vai, khu và đổi được giao diện', (tester) async {
    await ThemeController.load();
    await tester.pumpWidget(ValueListenableBuilder<ThemeMode>(
      valueListenable: ThemeController.mode,
      builder: (_, mode, __) => MaterialApp(
        theme: AppTheme.lightTheme,
        darkTheme: AppTheme.darkTheme,
        themeMode: mode,
        home: ProfileScreen(profile: _p()),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Hà Phi Vũ'), findsWidgets);
    expect(find.textContaining('Trẻ em'), findsOneWidget);
    expect(find.textContaining('Phòng ngủ'), findsOneWidget);
    expect(find.text('HV'), findsOneWidget);
    // Không có đăng nhập thật -> không có nút Đăng xuất.
    expect(find.text('Đăng xuất'), findsNothing);

    await tester.tap(find.text('Sáng'));
    await tester.pumpAndSettle();
    expect(ThemeController.mode.value, ThemeMode.light);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('theme_mode_v1'), 'light');
  });
}
