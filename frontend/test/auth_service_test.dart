import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:frontend/core/auth_service.dart';

/// Test cho đường xác thực, tập trung vào **isolate nền**.
///
/// Đây là đường hỏng ÂM THẦM: `widgetBackgroundCallback` và shortcut handler
/// chạy ở isolate riêng, nơi `Supabase.instance` chưa được khởi tạo. Nếu
/// `accessToken()` không rơi xuống app-token thì Home Widget hiện "Không rõ"
/// và nút bấm không làm gì — không báo lỗi, không crash, không ai biết.
/// Test chạy đúng trong điều kiện đó: Supabase CHƯA init.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('accessToken trong isolate nền (Supabase chưa init)', () {
    test('không có app-token thì trả null, KHÔNG ném lỗi', () async {
      expect(await AuthService.accessToken(), isNull);
    });

    test('có app-token thì trả đúng token đó', () async {
      SharedPreferences.setMockInitialValues({'app_token_v1': 'token-abc'});
      expect(await AuthService.accessToken(), 'token-abc');
    });

    test('app-token rỗng coi như không có', () async {
      SharedPreferences.setMockInitialValues({'app_token_v1': ''});
      expect(await AuthService.accessToken(), isNull);
    });
  });

  group('headers()', () {
    test('không có token thì ném NotAuthenticatedException', () async {
      expect(
        () => AuthService.headers(),
        throwsA(isA<NotAuthenticatedException>()),
      );
    });

    test('có token thì gắn Bearer', () async {
      SharedPreferences.setMockInitialValues({'app_token_v1': 'tok'});
      final h = await AuthService.headers();
      expect(h['Authorization'], 'Bearer tok');
      expect(h.containsKey('Content-Type'), isFalse);
    });

    test('jsonBody=true thêm Content-Type', () async {
      SharedPreferences.setMockInitialValues({'app_token_v1': 'tok'});
      final h = await AuthService.headers(jsonBody: true);
      expect(h['Content-Type'], 'application/json');
    });
  });

  group('clearAppToken', () {
    test('xóa xong thì accessToken trả null', () async {
      SharedPreferences.setMockInitialValues({'app_token_v1': 'tok'});
      expect(await AuthService.accessToken(), 'tok');
      await AuthService.clearAppToken();
      expect(await AuthService.accessToken(), isNull);
    });
  });

  group('HouseholdProfile', () {
    test('parse đủ field từ /api/me', () {
      final p = HouseholdProfile.fromJson({
        'user_id': 'u1',
        'email': 'a@x.test',
        'display_name': 'An',
        'role': 'kid',
        'status': 'active',
        'can_admin': false,
        'can_schedule': true,
        'zone_ids': [1, 2],
        'zones': [
          {'id': 1, 'name': 'Phòng khách', 'sort_order': 0},
        ],
      });
      expect(p.role, 'kid');
      expect(p.isActive, isTrue);
      expect(p.canAdmin, isFalse);
      expect(p.canSchedule, isTrue);
      expect(p.zoneIds, [1, 2]);
      expect(p.zones.first['name'], 'Phòng khách');
    });

    test('thiếu field thì về mặc định an toàn nhất (guest/pending)', () {
      final p = HouseholdProfile.fromJson({});
      expect(p.role, 'guest');
      expect(p.status, 'pending');
      expect(p.isPending, isTrue);
      expect(p.canAdmin, isFalse);
    });

    test('openHouse dùng khi backend chạy xác thực TẮT', () {
      // Không có nhánh này thì bản build chưa cấu hình Supabase sẽ kẹt ở màn
      // đăng nhập vĩnh viễn — không ai vào được nhà mình.
      expect(HouseholdProfile.openHouse.isActive, isTrue);
      expect(HouseholdProfile.openHouse.canAdmin, isTrue);
    });
  });
}
