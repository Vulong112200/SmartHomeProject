import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/core/device_type.dart';
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

  group('điều kiện kịch bản', () {
    test('kịch bản cũ (backend chưa trả conditions) = không điều kiện', () {
      final s = Scene.fromJson({'id': 1, 'name': 'Cũ', 'actions': []});
      expect(s.conditions.isEmpty, isTrue);
      expect(s.conditions.operator, 'AND');
    });

    test('parse + gửi lại nguyên vẹn, kể cả loại app chưa biết', () {
      final raw = {
        'operator': 'or',
        'items': [
          {'type': 'time_range', 'start': '22:00', 'end': '06:00', 'timezone': 'Asia/Ho_Chi_Minh'},
          {'type': 'device_state', 'device_id': 'pump', 'expected_state': 'off'},
          {'type': 'weather', 'rain': true},
        ],
      };
      final c = SceneConditions.fromJson(raw);
      expect(c.operator, 'OR');
      expect(c.items.first.isOvernight, isTrue);
      expect(c.toJson()['items'], raw['items']);
    });

    test('mô tả tiếng Việt', () {
      expect(describeSceneCondition(SceneCondition.time('22:00', '06:00'), _devices), 'Từ 22:00 đến 06:00 (qua đêm)');
      expect(describeSceneCondition(SceneCondition.time('08:00', '17:00'), _devices), 'Từ 08:00 đến 17:00');
      expect(describeSceneCondition(SceneCondition.device('pump', 'off'), _devices), 'Máy bơm đang tắt');
      expect(describeSceneCondition(SceneCondition.device('door', 'closed'), _devices), 'Cửa cuốn đang đóng');
      expect(describeSceneCondition(SceneCondition.device('ghost', 'off'), _devices), contains('đã xóa'));
    });

    test('trạng thái chọn được theo loại — máy cho ăn không làm điều kiện', () {
      expect(conditionStateOptions(DeviceType.curtain).map((o) => o.$1), ['closed', 'open']);
      expect(conditionStateOptions(DeviceType.powerSwitch).map((o) => o.$1), ['on', 'off']);
      expect(conditionStateOptions(DeviceType.feeder), isEmpty);
    });

    test('kết quả chạy: bỏ qua vì điều kiện', () {
      final r = SceneRunResult.fromResponse({
        'status': 'skipped',
        'message': 'Kịch bản đã bỏ qua: Không thỏa mãn điều kiện thực thi.',
        'data': {'executed': false, 'results': [], 'skipped': 0,
                 'conditions': {'result': 'failed', 'reason': 'Máy bơm đang bật (cần đang tắt)'}},
      });
      expect(r.conditionsBlocked, isTrue);
      expect(r.summary, 'Kịch bản đã bỏ qua: Không thỏa mãn điều kiện thực thi.\nMáy bơm đang bật (cần đang tắt)');
    });

    testWidgets('form hiện điều kiện có sẵn + cách kết hợp, xóa được', (tester) async {
      final scene = Scene(
        id: 7,
        name: 'Đi ngủ',
        actions: const [SceneAction('air', 'mode', 'sleep')],
        conditions: SceneConditions(operator: 'AND', items: [
          SceneCondition.time('22:00', '06:00'),
          SceneCondition.device('pump', 'off'),
        ]),
      );
      await tester.pumpWidget(MaterialApp(home: SceneEditorScreen(scene: scene, devices: _devices)));
      expect(find.text('Từ 22:00 đến 06:00 (qua đêm)'), findsOneWidget);
      expect(find.text('Máy bơm đang tắt'), findsOneWidget);
      expect(find.text('Tất cả đều đúng'), findsOneWidget);
      expect(find.text('VÀ'), findsOneWidget);

      await tester.tap(find.text('Chỉ cần 1 đúng'));
      await tester.pump();
      expect(find.text('HOẶC'), findsOneWidget);

      await tester.tap(find.byTooltip('Xóa điều kiện').first);
      await tester.pump();
      expect(find.text('Từ 22:00 đến 06:00 (qua đêm)'), findsNothing);
      expect(find.text('Chỉ cần 1 đúng'), findsNothing); // 1 điều kiện thì khỏi chọn cách kết hợp
    });

    test('kết quả chạy: thành công như cũ', () {
      final r = SceneRunResult.fromResponse({
        'status': 'success',
        'data': {'results': [{'success': true}, {'success': false}], 'skipped': 1},
      });
      expect((r.ok, r.failed, r.skipped, r.conditionsBlocked), (1, 1, 1, false));
    });
  });
}
