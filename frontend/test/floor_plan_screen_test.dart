import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/core/auth_service.dart';
import 'package:frontend/core/device_type.dart';
import 'package:frontend/core/floor_plan.dart';
import 'package:frontend/screens/floor_plan/device_control_sheet.dart';
import 'package:frontend/screens/floor_plan/floor_plan_tab.dart';
import 'package:frontend/theme/app_theme.dart';

/// Nguồn dữ liệu giả: KHÔNG gọi mạng, ghi lại mọi lệnh "gửi".
class _Fake {
  List<Map<String, dynamic>>? devices = [
    {'id': 'door1', 'name': 'Cửa cuốn', 'brand': 'tuya', 'category': 'curtain', 'zone_name': 'Nhà'},
    {'id': 'air1', 'name': 'Lọc không khí', 'brand': 'vesync', 'category': 'purifier'},
    {'id': 'pump1', 'name': 'Máy bơm tăng áp', 'brand': 'tuya', 'category': 'switch'},
    {'id': 'cat1', 'name': 'Máy cho mèo ăn', 'brand': 'rojeco', 'category': 'feeder'},
  ];
  FloorPlan plan = const FloorPlan(
    configured: true,
    rooms: [
      PlanRoom(id: 'main', name: 'Phòng chính', width: 4.09, depth: 3.00),
      PlanRoom(id: 'bath', name: 'Phòng tắm', width: 2.17, depth: 3.06, x: 4.09),
    ],
    devices: [
      DevicePlacement(deviceId: 'door1', roomId: 'main', x: 2.0, y: 2.8),
      DevicePlacement(deviceId: 'air1', roomId: 'main', x: 1.0, y: 1.0),
      DevicePlacement(deviceId: 'pump1', roomId: 'bath', x: 1.0, y: 1.5),
    ],
  );
  final Map<String, Map<String, dynamic>?> status = {
    'door1': {'status': 'ON', 'door_state': 'open'},
    'air1': {'status': 'OFF'},
    'pump1': {'status': 'offline'},
    'cat1': {'status': 'ON', 'feed_state': 'standby'},
  };
  final List<String> sent = [];
  bool sendOk = true;
  void Function(String id, DeviceActionOption o)? afterSend;
  FloorPlan? saved;
  int planFetches = 0;

  FloorPlanDataSource get source => FloorPlanDataSource(
        fetchDevices: () async => devices,
        fetchPlan: () async {
          planFetches++;
          return (plan, null);
        },
        savePlan: (p) async {
          saved = p;
          return (FloorPlan(rooms: p.rooms, doors: p.doors, devices: p.devices, configured: true), null);
        },
        fetchStatus: (brand, id, fresh) async => status[id],
        send: (brand, id, o) async {
          sent.add('$brand/$id ${o.key}');
          afterSend?.call(id, o);
          return sendOk;
        },
        confirmDelays: const [Duration(milliseconds: 20), Duration(milliseconds: 20)],
      );
}

const _kid = HouseholdProfile(
  userId: 'k', email: 'k@x', displayName: 'Bé', role: 'kid', status: 'active',
  canAdmin: false, canSchedule: true, zoneIds: [1], zones: [],
);

Future<void> _pump(WidgetTester tester, _Fake fake,
    {HouseholdProfile profile = HouseholdProfile.openHouse,
    TransformationController? controller,
    bool visible = true}) async {
  tester.view.physicalSize = const Size(1200, 2400); // 400 x 800 logic
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: AppTheme.darkTheme,
    home: Scaffold(
      body: FloorPlanTab(
        isVisible: visible,
        profile: profile,
        source: fake.source,
        transformationController: controller,
      ),
    ),
  ));
  await tester.pump(); // future tải devices + plan
  await tester.pump(); // future trạng thái
}

/// Gỡ widget ⇒ hủy timer poll 6s / thử lại 5s (test không được để timer treo).
Future<void> _unmount(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox());
}

/// Tâm icon thiết bị mong đợi (tọa độ toàn cục) theo đúng công thức mét -> px.
Offset _expectedCenter(WidgetTester tester, FloorPlan plan, String id) {
  final canvas = tester.getRect(find.byKey(const ValueKey('plan-canvas')));
  final view = plan.bounds.inflate(PlanGeometry.margin);
  final ppm = canvas.width / view.width; // đã gồm cả zoom (rect toàn cục)
  return canvas.topLeft + (plan.deviceCenter(id)! - view.topLeft) * ppm;
}

Offset _iconCenter(WidgetTester tester, String id) =>
    tester.getCenter(find.byKey(ValueKey('plan-device-icon-$id')));

void main() {
  testWidgets('icon nằm đúng tọa độ trong phòng, kể cả sau khi zoom + pan', (tester) async {
    final fake = _Fake();
    final ctl = TransformationController();
    await _pump(tester, fake, controller: ctl);

    for (final id in ['door1', 'air1', 'pump1']) {
      expect((_iconCenter(tester, id) - _expectedCenter(tester, fake.plan, id)).distance, lessThan(0.5), reason: id);
    }

    // Zoom 2.5x + kéo lệch.
    ctl.value = Matrix4.identity()
      ..setEntry(0, 0, 2.5)
      ..setEntry(1, 1, 2.5)
      ..setEntry(2, 2, 2.5)
      ..setEntry(0, 3, -150)
      ..setEntry(1, 3, -60);
    await tester.pump();
    for (final id in ['door1', 'air1', 'pump1']) {
      expect((_iconCenter(tester, id) - _expectedCenter(tester, fake.plan, id)).distance, lessThan(0.5), reason: id);
    }
    // Icon giữ nguyên kích thước trên màn hình khi zoom.
    expect(tester.getRect(find.byKey(const ValueKey('plan-device-icon-air1'))).width, closeTo(44, 0.5));

    // Tỷ lệ 2 phòng trên màn hình đúng bằng tỷ lệ thật (ppm chung).
    final canvas = tester.getRect(find.byKey(const ValueKey('plan-canvas')));
    final view = fake.plan.bounds.inflate(PlanGeometry.margin);
    expect(canvas.width / canvas.height, closeTo(view.width / view.height, 1e-3));
    await _unmount(tester);
  });

  testWidgets('chạm icon mở ĐÚNG thiết bị; lệnh đi qua API, chỉ báo xác nhận khi trạng thái thật đổi',
      (tester) async {
    final fake = _Fake();
    fake.afterSend = (id, o) => fake.status[id] = {'status': 'ON', 'door_state': 'closing'};
    await _pump(tester, fake);

    await tester.tap(find.byKey(const ValueKey('plan-device-icon-door1')));
    await tester.pump();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    final panel = find.byType(DeviceControlPanel);
    expect(panel, findsOneWidget);
    expect(find.descendant(of: panel, matching: find.text('Cửa cuốn')), findsOneWidget);
    // Cửa chỉ mở/dừng/đóng — không có bật/tắt.
    expect(find.descendant(of: panel, matching: find.byType(ChoiceChip)), findsNWidgets(3));
    expect(find.descendant(of: panel, matching: find.text('Bật')), findsNothing);

    await tester.tap(find.byKey(const ValueKey('plan-action-mode:close')));
    await tester.pump();
    expect(fake.sent, ['tuya/door1 mode:close']);
    expect(find.textContaining('chờ thiết bị xác nhận'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 25));
    await tester.pump();
    expect(find.text('Đã xác nhận: Đóng cửa'), findsOneWidget);
    expect(find.descendant(of: panel, matching: find.text('Nhà • Đang đóng...')), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('lệnh lỗi KHÔNG được báo thành công', (tester) async {
    final fake = _Fake()..sendOk = false;
    await _pump(tester, fake);
    await tester.tap(find.byKey(const ValueKey('plan-device-icon-air1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.byKey(const ValueKey('plan-action-on:')));
    await tester.pump();
    await tester.pump();
    expect(fake.sent, ['vesync/air1 on:']);
    expect(find.textContaining('Thiết bị không nhận lệnh'), findsOneWidget);
    expect(find.textContaining('Đã xác nhận'), findsNothing);
    await _unmount(tester);
  });

  testWidgets('gửi được nhưng thiết bị không đổi trạng thái -> cảnh báo, không "xác nhận"', (tester) async {
    final fake = _Fake(); // trạng thái máy lọc giữ nguyên OFF
    await _pump(tester, fake);
    await tester.tap(find.byKey(const ValueKey('plan-device-icon-air1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.byKey(const ValueKey('plan-action-mode:3')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 25));
    await tester.pump(const Duration(milliseconds: 25));
    await tester.pump();
    expect(find.textContaining('chưa báo trạng thái mới'), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('thiết bị mất kết nối hiện rõ trên icon', (tester) async {
    final fake = _Fake();
    await _pump(tester, fake);
    expect(find.text('Mất kết nối'), findsWidgets);
    expect(find.byIcon(Icons.cloud_off), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('máy chủ không trả lời -> banner mất kết nối, không vỡ màn hình', (tester) async {
    final fake = _Fake()..devices = null;
    await _pump(tester, fake);
    expect(find.byKey(const ValueKey('plan-offline-banner')), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('thiết bị chưa đặt nằm ở hàng dưới, vẫn chạm điều khiển được; máy cho ăn tối đa 3 phần',
      (tester) async {
    final fake = _Fake();
    await _pump(tester, fake);
    expect(find.byKey(const ValueKey('plan-marker-cat1')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('plan-tray-cat1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    final panel = find.byType(DeviceControlPanel);
    expect(find.descendant(of: panel, matching: find.byType(ChoiceChip)), findsNWidgets(3));
    expect(find.descendant(of: panel, matching: find.text('Nhả 3 phần')), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('trẻ em không có nút Sửa; chưa cấu hình thì có lời nhắc', (tester) async {
    final fake = _Fake()..plan = const FloorPlan(rooms: [PlanRoom(id: 'main', name: 'P', width: 4.09, depth: 3)]);
    await _pump(tester, fake, profile: _kid);
    expect(find.byKey(const ValueKey('plan-edit')), findsNothing);
    expect(find.byKey(const ValueKey('plan-not-configured')), findsOneWidget);
    await _unmount(tester);
  });

  testWidgets('chủ nhà: đặt thiết bị vào phòng, kéo tới chỗ mới, lưu', (tester) async {
    final fake = _Fake();
    await _pump(tester, fake);
    await tester.tap(find.byKey(const ValueKey('plan-edit')));
    await tester.pump();

    // Đặt máy cho ăn vào Phòng tắm.
    await tester.tap(find.byKey(const ValueKey('plan-tray-cat1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text('Phòng tắm').last);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byKey(const ValueKey('plan-marker-cat1')), findsOneWidget);

    // Kéo máy lọc 1 đoạn sang phải.
    final before = _iconCenter(tester, 'air1');
    final gesture = await tester.startGesture(before);
    await gesture.moveBy(const Offset(30, 0));
    await gesture.moveBy(const Offset(30, 0));
    await gesture.up();
    await tester.pump();
    expect(_iconCenter(tester, 'air1').dx, greaterThan(before.dx + 40));

    await tester.tap(find.byKey(const ValueKey('plan-save')));
    await tester.pump();
    await tester.pump();
    final saved = fake.saved!;
    expect(saved.placement('cat1')!.roomId, 'bath');
    expect(saved.placement('air1')!.x, greaterThan(1.2));
    expect(find.byKey(const ValueKey('plan-save')), findsNothing); // đã thoát chế độ sửa
    await _unmount(tester);
  });

  testWidgets('tab chưa mở thì chưa tải gì (không thêm tải lúc khởi động app)', (tester) async {
    final fake = _Fake();
    await _pump(tester, fake, visible: false);
    expect(fake.planFetches, 0);
    await _unmount(tester);
  });
}
