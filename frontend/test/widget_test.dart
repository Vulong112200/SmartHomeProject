import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:frontend/core/auth_service.dart';
import 'package:frontend/screens/auth_gate.dart';
import 'package:frontend/screens/pending_screen.dart';

/// Test cho AuthGate. (File này trước đây là template đếm số mặc định của
/// Flutter — không liên quan gì tới app và sẽ fail nếu chạy.)
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('chưa cấu hình Supabase thì vào thẳng app, không kẹt ở màn login',
      (tester) async {
    // AppConfig.authEnabled = false khi build không truyền --dart-define.
    // Đây là bản build hiện tại đang chạy trên điện thoại cả nhà.
    await tester.pumpWidget(MaterialApp(
      home: AuthGate(
        builder: (profile) => Scaffold(
          body: Text('APP ${profile.role}'),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('APP owner'), findsOneWidget);
  });

  testWidgets('PendingScreen hiện lý do chờ duyệt kèm email', (tester) async {
    const profile = HouseholdProfile(
      userId: 'u1',
      email: 'con@x.test',
      displayName: 'Con',
      role: 'guest',
      status: 'pending',
      canAdmin: false,
      canSchedule: false,
      zoneIds: [],
      zones: [],
    );

    await tester.pumpWidget(MaterialApp(
      home: PendingScreen(
        profile: profile,
        onRetry: () async {},
        onSignOut: () {},
      ),
    ));

    expect(find.text('Chưa thuộc nhà nào'), findsOneWidget);
    expect(find.textContaining('con@x.test'), findsOneWidget);
  });

  testWidgets('bị chặn thì hiện thông báo khác, không có nút kiểm tra lại',
      (tester) async {
    const profile = HouseholdProfile(
      userId: 'u2',
      email: 'x@x.test',
      displayName: 'X',
      role: 'guest',
      status: 'blocked',
      canAdmin: false,
      canSchedule: false,
      zoneIds: [],
      zones: [],
    );

    await tester.pumpWidget(MaterialApp(
      home: PendingScreen(
        profile: profile,
        onRetry: () async {},
        onSignOut: () {},
      ),
    ));

    expect(find.text('Tài khoản đã bị chặn'), findsOneWidget);
    expect(find.text('Kiểm tra lại'), findsNothing);
  });
}
