import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:frontend/core/auth_service.dart';
import 'package:frontend/screens/admin_screen.dart';
import 'package:frontend/screens/forgot_password_screen.dart';
import 'package:frontend/screens/help_screen.dart';
import 'package:frontend/screens/login_screen.dart';
import 'package:frontend/screens/onboarding_screen.dart';
import 'package:frontend/screens/password_field.dart';
import 'package:frontend/theme/app_theme.dart';

HouseholdProfile _as(String role) => HouseholdProfile(
      userId: 'u',
      email: 'u@x.test',
      displayName: 'U',
      role: role,
      status: 'active',
      canAdmin: role == 'owner',
      canSchedule: role != 'guest',
      zoneIds: const [],
      zones: const [],
    );

Widget _app(Widget home) => MaterialApp(theme: AppTheme.darkTheme, home: home);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('tìm kiếm không phân biệt dấu', () {
    expect(foldVietnamese('Hà Phi Vũ'), 'ha phi vu');
    expect(foldVietnamese('Đặng ĐỨC'), 'dang duc');
    expect(foldVietnamese('Cô Hoa').contains(foldVietnamese('hoa')), isTrue);
  });

  testWidgets('"Quên mật khẩu?" chỉ hiện ở chế độ đăng nhập', (tester) async {
    await tester.pumpWidget(_app(LoginScreen(onSignedIn: () {})));
    expect(find.text('Quên mật khẩu?'), findsOneWidget);
    await tester.tap(find.text('Chưa có tài khoản? Đăng ký'));
    await tester.pump();
    expect(find.text('Quên mật khẩu?'), findsNothing);
  });

  testWidgets('nút con mắt ẩn/hiện mật khẩu', (tester) async {
    final ctrl = TextEditingController(text: 'bimat');
    await tester.pumpWidget(_app(Scaffold(body: PasswordField(controller: ctrl))));
    TextField field() => tester.widget<TextField>(find.byType(TextField));
    expect(field().obscureText, isTrue);
    await tester.tap(find.byIcon(Icons.visibility_off));
    await tester.pump();
    expect(field().obscureText, isFalse);
  });

  testWidgets('quên mật khẩu: email sai thì không gửi', (tester) async {
    await tester.pumpWidget(_app(const ForgotPasswordScreen(initialEmail: 'khong-phai-email')));
    await tester.tap(find.text('Gửi mã'));
    await tester.pump();
    expect(find.text('Email không hợp lệ'), findsOneWidget);
  });

  test('luật mật khẩu mới', () {
    expect(validateNewPassword('12345'), isNotNull);
    expect(validateNewPassword('123456'), isNull);
    expect(friendlyAuthError('Token has expired or is invalid'), contains('Mã không đúng'));
    expect(friendlyAuthError('Invalid login credentials'), 'Email hoặc mật khẩu không đúng.');
  });

  testWidgets('hướng dẫn: mục Quản trị chỉ chủ nhà thấy', (tester) async {
    // Mục Quản trị ở cuối danh sách: cuộn hết rồi mới kết luận có/không.
    Future<void> scrollToEnd() async {
      await tester.drag(find.byType(ListView), const Offset(0, -3000));
      await tester.pumpAndSettle();
    }

    await tester.pumpWidget(_app(HelpScreen(profile: _as('kid'))));
    expect(find.text('Trợ lý giọng nói'), findsOneWidget);
    await scrollToEnd();
    expect(find.text('Quản trị nhà (chủ nhà)'), findsNothing);

    await tester.pumpWidget(_app(HelpScreen(profile: _as('owner'))));
    await scrollToEnd();
    expect(find.text('Quản trị nhà (chủ nhà)'), findsOneWidget);
  });

  testWidgets('giới thiệu lần đầu chỉ hiện 1 lần', (tester) async {
    late BuildContext ctx;
    await tester.pumpWidget(_app(Builder(builder: (c) {
      ctx = c;
      return const SizedBox();
    })));

    OnboardingScreen.showIfFirstTime(ctx);
    await tester.pumpAndSettle();
    expect(find.text('Chào mừng về nhà'), findsOneWidget);
    await tester.tap(find.text('Bỏ qua'));
    await tester.pumpAndSettle();

    OnboardingScreen.showIfFirstTime(ctx);
    await tester.pumpAndSettle();
    expect(find.text('Chào mừng về nhà'), findsNothing);
  });
}
