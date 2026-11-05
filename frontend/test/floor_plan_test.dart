import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/core/device_status.dart';
import 'package:frontend/core/device_type.dart';
import 'package:frontend/core/floor_plan.dart';

const _main = PlanRoom(id: 'main', name: 'Phòng chính', width: 4.09, depth: 3.00);
const _bath = PlanRoom(id: 'bath', name: 'Phòng tắm', width: 2.17, depth: 3.06, x: 4.09);
const _plan = FloorPlan(rooms: [_main, _bath], devices: [
  DevicePlacement(deviceId: 'air', roomId: 'main', x: 1, y: 1),
  DevicePlacement(deviceId: 'pump', roomId: 'bath', x: 1, y: 1.5),
]);

Matcher _near(Offset o) => isA<Offset>()
    .having((v) => (v - o).distance, 'khoảng cách tới $o', lessThan(1e-6));

void main() {
  group('Tỷ lệ', () {
    test('2 phòng dùng CHUNG một tỷ lệ — kích thước trên màn hình tỷ lệ đúng với mét thật', () {
      for (final size in const [Size(360, 500), Size(412, 300), Size(1024, 700)]) {
        final g = PlanGeometry.fit(_plan, size);
        final m = g.rectToPx(_main.rect);
        final b = g.rectToPx(_bath.rect);
        expect(m.width / b.width, closeTo(4.09 / 2.17, 1e-9));
        expect(m.height / b.height, closeTo(3.00 / 3.06, 1e-9));
        expect(m.width / m.height, closeTo(4.09 / 3.00, 1e-9), reason: 'không kéo giãn 1 trục');
        // Vừa khít khung, không tràn.
        expect(g.size.width, lessThanOrEqualTo(size.width + 1e-9));
        expect(g.size.height, lessThanOrEqualTo(size.height + 1e-9));
      }
    });

    test('mét <-> pixel đổi qua lại không lệch', () {
      final g = PlanGeometry.fit(_plan, const Size(390, 600));
      const p = Offset(5.2, 1.7);
      expect(g.toMeters(g.toPx(p)), _near(p));
    });

    test('phòng chung tường nằm sát nhau trên màn hình', () {
      final g = PlanGeometry.fit(_plan, const Size(390, 600));
      expect(g.rectToPx(_main.rect).right, closeTo(g.rectToPx(_bath.rect).left, 1e-9));
    });
  });

  group('JSON', () {
    test('đọc/ghi giữ nguyên dữ liệu (khớp shape backend)', () {
      final j = {
        'rooms': [_main.toJson(), _bath.toJson()],
        'doors': [
          {'id': 'd1', 'room': 'main', 'wall': 'bottom', 'offset': 1.0, 'width': 0.9}
        ],
        'devices': [
          {'device_id': 'air', 'room': 'main', 'x': 1.0, 'y': 1.0}
        ],
        'configured': true,
      };
      final plan = FloorPlan.fromJson(j);
      expect(plan.configured, isTrue);
      expect(plan.doors.single.wall, Wall.bottom);
      final back = plan.toJson();
      expect(back['rooms'], j['rooms']);
      expect(back['doors'], j['doors']);
      expect(back['devices'], j['devices']);
    });

    test('dữ liệu thiếu/sai kiểu không làm vỡ app', () {
      final plan = FloorPlan.fromJson({
        'rooms': [
          {'id': 'r', 'name': 'X', 'width': 'abc'}
        ],
        'doors': 'không phải list',
      });
      expect(plan.rooms.single.width, 1);
      expect(plan.doors, isEmpty);
      expect(plan.configured, isFalse);
    });
  });

  group('Vị trí thiết bị theo mét trong phòng', () {
    test('tâm thiết bị = góc phòng + tọa độ trong phòng', () {
      expect(_plan.deviceCenter('pump'), _near(const Offset(4.09 + 1, 1.5)));
      expect(_plan.deviceCenter('ghost'), isNull);
    });

    test('kéo thiết bị sang phòng khác: tự đổi phòng, tọa độ tính lại theo phòng mới', () {
      final p = _plan.moveDevice('air', const Offset(5.0, 2.0));
      final placed = p.placement('air')!;
      expect(placed.roomId, 'bath');
      expect(placed.x, closeTo(5.0 - 4.09, 1e-9));
      expect(p.deviceCenter('air'), _near(const Offset(5.0, 2.0)));
    });

    test('thả ra ngoài mọi phòng: kẹp vào phòng gần nhất, không bao giờ nằm ngoài', () {
      final p = _plan.moveDevice('air', const Offset(-3, 10));
      final placed = p.placement('air')!;
      expect((placed.roomId, placed.x, placed.y), ('main', 0.0, 3.0));
    });

    test('di chuyển phòng thì thiết bị đi theo', () {
      final p = _plan.moveRoom('bath', const Offset(0, 3.0));
      expect(p.deviceCenter('pump'), _near(const Offset(1, 3.0 + 1.5)));
    });

    test('kéo thiết bị KHÔNG tạo danh sách phòng/cửa mới (phần vẽ tường khỏi vẽ lại)', () {
      final p = _plan.moveDevice('air', const Offset(2, 2));
      expect(identical(p.rooms, _plan.rooms), isTrue);
      expect(identical(p.doors, _plan.doors), isTrue);
    });

    test('đặt thiết bị chưa có vị trí vào giữa phòng đã chọn', () {
      final p = _plan.placeDevice('door', 'bath');
      expect(p.placement('door')!.roomId, 'bath');
      expect(p.devices.length, 3);
      expect(p.removeDevice('door').placement('door'), isNull);
    });
  });

  group('Sửa phòng / cửa', () {
    test('kéo phòng gần mép phòng kia thì hút khít, không hở vài cm', () {
      final p = _plan.moveRoom('bath', const Offset(4.21, 0.13));
      expect(p.room('bath')!.x, closeTo(4.09, 1e-9));
      expect(p.room('bath')!.y, closeTo(0, 1e-9));
    });

    test('xa mép thì chỉ hút lưới 5 cm', () {
      final p = _plan.moveRoom('bath', const Offset(5.02, 1.33));
      expect(p.room('bath')!.x, closeTo(5.0, 1e-9));
      expect(p.room('bath')!.y, closeTo(1.35, 1e-9));
    });

    test('thêm cửa: giữa tường, rộng 0,8 m, id không trùng', () {
      var p = _plan.addDoor('main', Wall.bottom);
      p = p.addDoor('main', Wall.bottom);
      expect(p.doors.map((d) => d.id).toSet().length, 2);
      final d = p.doors.first;
      expect(d.width, 0.8);
      expect(d.offset, closeTo((4.09 - 0.8) / 2, 1e-3));
    });

    test('trượt cửa bị kẹp trong tường', () {
      var p = _plan.addDoor('main', Wall.left, id: 'd');
      p = p.slideDoor('d', const Offset(0, 99));
      final d = p.doors.single;
      expect(d.offset + d.width, closeTo(3.0, 1e-9));
      p = p.slideDoor('d', const Offset(0, -5));
      expect(p.doors.single.offset, 0);
    });

    test('đổi bề rộng cửa giữ tâm; thu nhỏ phòng thì cửa/thiết bị kẹp lại', () {
      var p = _plan.addDoor('main', Wall.top, id: 'd'); // offset 1.645, rộng 0.8 -> tâm 2.045
      p = p.resizeDoor('d', 1.2);
      expect(p.doors.single.offset + 0.6, closeTo(2.045, 1e-3));
      p = p.resizeRoom('main', width: 1.0, depth: 0.8);
      expect(p.doors.single.width, lessThanOrEqualTo(1.0));
      final air = p.placement('air')!;
      expect((air.x, air.y), (1.0, 0.8));
    });
  });

  group('Diễn giải trạng thái', () {
    test('cửa: mở/đóng/đang chạy/mất kết nối', () {
      expect(describeDeviceStatus(DeviceType.curtain, {'status': 'ON', 'door_state': 'open'}).state,
          DeviceVisualState.active);
      expect(describeDeviceStatus(DeviceType.curtain, {'status': 'OFF', 'door_state': 'closed'}).label, 'Đã đóng');
      expect(describeDeviceStatus(DeviceType.curtain, {'status': 'ON', 'door_state': 'closing'}).state,
          DeviceVisualState.moving);
      expect(describeDeviceStatus(DeviceType.curtain, {'status': 'offline'}).state, DeviceVisualState.offline);
      expect(describeDeviceStatus(DeviceType.curtain, null).state, DeviceVisualState.unknown);
    });

    test('máy lọc / máy bơm / máy cho ăn', () {
      final air = describeDeviceStatus(DeviceType.airPurifier, {'status': 'ON', 'mode': 'manual', 'speed': 3});
      expect((air.state, air.label), (DeviceVisualState.active, 'Đang chạy: Lọc Cao'));
      expect(describeDeviceStatus(DeviceType.powerSwitch, {'status': 'OFF'}).state, DeviceVisualState.idle);
      expect(describeDeviceStatus(DeviceType.feeder, {'status': 'ON', 'feed_state': 'feeding'}).state,
          DeviceVisualState.moving);
      expect(describeDeviceStatus(DeviceType.feeder, {'status': 'OFF'}).label, 'Mất kết nối');
    });

    test('lệnh chỉ được coi là xác nhận khi trạng thái THẬT khớp', () {
      const close = DeviceActionOption('Đóng cửa', 'mode', 'close');
      expect(statusConfirms(DeviceType.curtain, close, {'status': 'ON', 'door_state': 'open'}), isFalse);
      expect(statusConfirms(DeviceType.curtain, close, {'status': 'ON', 'door_state': 'closing'}), isTrue);
      expect(statusConfirms(DeviceType.curtain, close, null), isFalse);
      expect(statusConfirms(DeviceType.curtain, close, {'status': 'offline'}), isFalse);
      const on = DeviceActionOption('Bật', 'on');
      expect(statusConfirms(DeviceType.airPurifier, on, {'status': 'ON', 'mode': 'auto'}), isTrue);
      const low = DeviceActionOption('Lọc Thấp', 'mode', '1');
      expect(statusConfirms(DeviceType.airPurifier, low, {'status': 'ON', 'mode': 'manual', 'speed': 3}), isFalse);
    });

    test('máy cho ăn không poll định kỳ (tiết kiệm quota Tuya)', () {
      expect(needsPolling(DeviceType.feeder), isFalse);
      expect(needsPolling(DeviceType.curtain), isTrue);
    });
  });
}
