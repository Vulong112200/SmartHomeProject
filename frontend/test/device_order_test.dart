import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:frontend/core/auth_service.dart';
import 'package:frontend/core/device_order.dart';

List<Map<String, dynamic>> _devices(List<String> ids) => [for (final id in ids) {'id': id, 'name': id}];
List<String> _ids(List<dynamic> devices) => [for (final d in devices) '${d['id']}'];

/// Bộ gửi giả: ghi lại mỗi lần gửi, trả kết quả theo [results] (hết thì true).
class _FakeSender {
  final List<List<String>> calls = [];
  final List<bool> results;
  _FakeSender([List<bool>? results]) : results = results ?? [];

  Future<bool> call(List<String> ids) async {
    calls.add(ids);
    return results.isEmpty ? true : results.removeAt(0);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('DeviceOrder.apply', () {
    test('sắp theo id đã lưu, thiết bị mới xuống cuối theo thứ tự backend', () {
      final out = DeviceOrder.apply(_devices(['a', 'b', 'c', 'new1', 'new2']), ['c', 'a', 'b']);
      expect(_ids(out), ['c', 'a', 'b', 'new1', 'new2']);
    });

    test('id đã xóa / mất quyền bị bỏ qua, không lỗi', () {
      final out = DeviceOrder.apply(_devices(['a', 'b']), ['gone', 'b', 'a', 'gone2']);
      expect(_ids(out), ['b', 'a']);
    });

    test('thứ tự rỗng = giữ thứ tự backend; id trùng lấy vị trí đầu', () {
      expect(_ids(DeviceOrder.apply(_devices(['a', 'b']), [])), ['a', 'b']);
      expect(_ids(DeviceOrder.apply(_devices(['a', 'b']), ['b', 'a', 'b'])), ['b', 'a']);
    });
  });

  group('HouseholdProfile.sortOrder', () {
    Map<String, dynamic> base() => {'user_id': 'u1', 'role': 'adult', 'status': 'active'};

    test('đọc sort_order từ /api/me', () {
      final p = HouseholdProfile.fromJson({...base(), 'sort_order': ['x', 'y']});
      expect(p.sortOrder, ['x', 'y']);
    });

    test('backend cũ không có trường / sai kiểu -> rỗng; phần tử không phải chuỗi bị bỏ', () {
      expect(HouseholdProfile.fromJson(base()).sortOrder, isEmpty);
      expect(HouseholdProfile.fromJson({...base(), 'sort_order': 'abc'}).sortOrder, isEmpty);
      expect(HouseholdProfile.fromJson({...base(), 'sort_order': [1, 'a', null]}).sortOrder, ['a']);
    });

    test('copyWith (sửa tên ở Hồ sơ) giữ nguyên thứ tự', () {
      final p = HouseholdProfile.fromJson({...base(), 'sort_order': ['x']});
      expect(p.copyWith(displayName: 'Mẹ').sortOrder, ['x']);
    });
  });

  group('DeviceOrderSync', () {
    testWidgets('kéo-thả liên tiếp: chỉ gửi bản cuối, sau 2s kể từ lần kéo cuối', (tester) async {
      final sender = _FakeSender();
      final sync = DeviceOrderSync(userId: 'u1', send: sender.call);

      sync.schedule(['a', 'b', 'c']);
      await tester.pump(const Duration(milliseconds: 1500));
      sync.schedule(['b', 'a', 'c']);
      await tester.pump(const Duration(milliseconds: 1500));
      sync.schedule(['c', 'b', 'a']);
      await tester.pump(const Duration(milliseconds: 1900));
      expect(sender.calls, isEmpty); // chưa đủ 2s từ lần kéo cuối

      await tester.pump(const Duration(milliseconds: 200));
      expect(sender.calls, [
        ['c', 'b', 'a']
      ]);
      expect(sync.hasPending, isFalse);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getStringList('device_order_pending_v2:u1'), isNull);
      sync.dispose();
    });

    testWidgets('gửi lỗi -> giữ bản chờ, thử lại tới khi được', (tester) async {
      final sender = _FakeSender([false, false]);
      final sync = DeviceOrderSync(userId: 'u1', send: sender.call);

      sync.schedule(['a', 'b']);
      await tester.pump(const Duration(seconds: 2));
      expect(sender.calls.length, 1);
      expect(sync.isRetrying, isTrue);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getStringList('device_order_pending_v2:u1'), ['a', 'b']);

      await tester.pump(const Duration(seconds: 5)); // lần thử 2 (lỗi)
      expect(sender.calls.length, 2);
      await tester.pump(const Duration(seconds: 15)); // lần thử 3 (được)
      expect(sender.calls.length, 3);
      expect(sync.hasPending, isFalse);
      expect(prefs.getStringList('device_order_pending_v2:u1'), isNull);
      sync.dispose();
    });

    testWidgets('flush gửi ngay, không chờ debounce', (tester) async {
      final sender = _FakeSender();
      final sync = DeviceOrderSync(userId: 'u1', send: sender.call);
      sync.schedule(['x']);
      await sync.flush();
      expect(sender.calls, [
        ['x']
      ]);
      await tester.pump(const Duration(seconds: 3)); // hẹn cũ đã bị hủy -> không gửi lặp
      expect(sender.calls.length, 1);
      sync.dispose();
    });

    testWidgets('kéo tiếp trong lúc đang gửi: bản mới vẫn được gửi sau', (tester) async {
      final calls = <List<String>>[];
      late DeviceOrderSync sync;
      sync = DeviceOrderSync(
        userId: 'u1',
        send: (ids) async {
          calls.add(ids);
          if (calls.length == 1) sync.schedule(['new']); // người dùng kéo tiếp giữa chừng
          return true;
        },
      );
      sync.schedule(['old']);
      await tester.pump(const Duration(seconds: 2));
      expect(sync.pending, ['new']); // bản mới KHÔNG bị xóa nhầm
      await tester.pump(const Duration(seconds: 2));
      expect(calls, [
        ['old'],
        ['new']
      ]);
      expect(sync.hasPending, isFalse);
      sync.dispose();
    });

    testWidgets('app bị tắt trước khi gửi -> lần mở sau nạp lại bản chờ', (tester) async {
      final first = DeviceOrderSync(userId: 'u1', send: _FakeSender().call);
      first.schedule(['b', 'a']);
      await tester.pump(); // ghi xuống SharedPreferences
      first.dispose(); // app chết trước 2s

      final sender = _FakeSender();
      final next = DeviceOrderSync(userId: 'u1', send: sender.call);
      await next.restore();
      expect(next.pending, ['b', 'a']);
      await next.flush();
      expect(sender.calls, [
        ['b', 'a']
      ]);

      // Tài khoản khác trên cùng máy không thấy bản chờ này.
      final other = DeviceOrderSync(userId: 'u2', send: _FakeSender().call);
      await other.restore();
      expect(other.hasPending, isFalse);
      next.dispose();
      other.dispose();
    });

    testWidgets('sau dispose không còn hẹn thử lại', (tester) async {
      final sender = _FakeSender([false]);
      final sync = DeviceOrderSync(userId: 'u1', send: sender.call);
      sync.schedule(['a']);
      await sync.flush(); // lỗi
      sync.dispose();
      await tester.pump(const Duration(minutes: 2));
      expect(sender.calls.length, 1);
    });
  });
}
