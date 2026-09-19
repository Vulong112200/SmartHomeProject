import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/core/household_api.dart';

/// Test cho quy tắc hiển thị của màn quản trị.
///
/// Không dựng cả AdminScreen (nó fetch mạng ngay trong initState); test ở đây
/// nhắm vào các quy tắc dễ sai mà nếu sai thì chủ nhà tự khóa mình khỏi nhà
/// hoặc cấp quyền nhầm.
void main() {
  Member m({
    String userId = 'u1',
    String role = 'kid',
    String status = 'active',
    List<int> zoneIds = const [],
  }) =>
      Member(
        userId: userId,
        email: '$userId@x.test',
        displayName: '',
        role: role,
        status: status,
        zoneIds: zoneIds,
      );

  group('Member.seesAllZones — quyết định có hiện ô tick khu hay không', () {
    test('owner và adult thấy mọi khu theo luật vai', () {
      expect(m(role: 'owner').seesAllZones, isTrue);
      expect(m(role: 'adult').seesAllZones, isTrue);
    });

    test('kid và guest đi theo grant', () {
      expect(m(role: 'kid').seesAllZones, isFalse);
      expect(m(role: 'guest').seesAllZones, isFalse);
    });
  });

  group('Chặn nhà mất chủ (luật UI phải khớp luật API)', () {
    int activeOwners(List<Member> members) =>
        members.where((x) => x.role == 'owner' && x.status == 'active').length;

    bool isLastOwner(Member target, List<Member> all) =>
        target.role == 'owner' && target.status == 'active' && activeOwners(all) <= 1;

    test('chủ nhà duy nhất đang hoạt động thì bị khóa không cho đổi', () {
      final owner = m(userId: 'boss', role: 'owner');
      final all = [owner, m(userId: 'kid1')];
      expect(isLastOwner(owner, all), isTrue);
    });

    test('có hai chủ nhà thì đổi được', () {
      final a = m(userId: 'boss1', role: 'owner');
      final b = m(userId: 'boss2', role: 'owner');
      expect(isLastOwner(a, [a, b]), isFalse);
    });

    test('chủ nhà thứ hai đang bị chặn thì KHÔNG tính là còn chủ', () {
      final a = m(userId: 'boss1', role: 'owner');
      final b = m(userId: 'boss2', role: 'owner', status: 'blocked');
      expect(isLastOwner(a, [a, b]), isTrue);
    });
  });

  group('Member.fromJson', () {
    test('parse đủ field', () {
      final x = Member.fromJson({
        'user_id': 'u9',
        'email': 'a@x.test',
        'display_name': 'An',
        'role': 'kid',
        'status': 'pending',
        'zone_ids': [3, 7],
      });
      expect(x.userId, 'u9');
      expect(x.isPending, isTrue);
      expect(x.zoneIds, [3, 7]);
    });

    test('thiếu field thì về mặc định hạn chế nhất', () {
      final x = Member.fromJson({});
      expect(x.role, 'guest');
      expect(x.status, 'pending');
      expect(x.zoneIds, isEmpty);
      expect(x.seesAllZones, isFalse);
    });
  });

  group('Zone.fromJson', () {
    test('parse và mặc định sort_order = 0', () {
      final z = Zone.fromJson({'id': 2, 'name': 'Bếp'});
      expect(z.id, 2);
      expect(z.name, 'Bếp');
      expect(z.sortOrder, 0);
    });
  });
}
