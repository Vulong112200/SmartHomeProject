import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/core/scene_api.dart';
import 'package:frontend/core/zone_groups.dart';
import 'package:frontend/screens/scene_editor_screen.dart';

final _devices = [
  {'id': 'door', 'name': 'Cửa cuốn', 'zone_id': 3, 'zone_name': 'Toàn nhà', 'zone_shared': true, 'is_active': true},
  {'id': 'air', 'name': 'Lọc không khí', 'zone_id': 1, 'zone_name': 'Phòng khách', 'is_active': false},
  {'id': 'pump', 'name': 'Máy bơm', 'category': 'switch', 'zone_id': 3, 'zone_name': 'Toàn nhà', 'zone_shared': true, 'is_active': false},
  {'id': 'new', 'name': 'Ổ cắm mới', 'zone_id': null, 'is_active': true},
];

void main() {
  test('gom theo khu, đúng thứ tự backend, "Chưa phân khu" ở cuối', () {
    final groups = zoneGroupsOf(_devices, ['1', '3', 'none']);
    expect(groups.map((g) => g.name), ['Phòng khách', 'Toàn nhà', 'Chưa phân khu']);
    final home = groups[1];
    expect((home.total, home.on, home.shared), (2, 1, true));
  });

  test('khu không có trong thứ tự backend vẫn hiện, xếp sau', () {
    final groups = zoneGroupsOf(_devices, ['3']);
    expect(groups.map((g) => g.key), ['3', '1', 'none']);
  });

  test('lọc theo khu giữ nguyên thứ tự người dùng đã sắp', () {
    expect(devicesInZone(_devices, '3').map((d) => d['id']), ['door', 'pump']);
    expect(devicesInZone(_devices, allZonesKey).length, 4);
    expect(devicesInZone(_devices, unassignedKey).map((d) => d['id']), ['new']);
  });

  test('kịch bản có MỞ CỬA thì cần xác nhận, đóng cửa thì không', () {
    const open = Scene(id: 1, name: 'Về nhà', actions: [SceneAction('door', 'mode', 'open')]);
    const close = Scene(id: 2, name: 'Ra khỏi nhà', actions: [
      SceneAction('door', 'mode', 'close'),
      SceneAction('pump', 'off'),
    ]);
    expect(sceneOpensDoor(open, _devices), isTrue);
    expect(sceneOpensDoor(close, _devices), isFalse);
  });

  test('parse kịch bản và tóm tắt kết quả chạy', () {
    final s = Scene.fromJson({
      'id': 5, 'name': 'Đi ngủ', 'icon': 'bedtime',
      'actions': [{'device_id': 'air', 'action_type': 'mode', 'action_value': 'sleep'}],
    });
    expect((s.id, s.name, s.actions.single.actionValue), (5, 'Đi ngủ', 'sleep'));
    expect(const SceneRunResult(2, 0, 1).summary, '2 xong • 1 bỏ qua (ngoài khu)');
    expect(const SceneRunResult(0, 0, 0).summary, 'Không có hành động nào');
  });
}
