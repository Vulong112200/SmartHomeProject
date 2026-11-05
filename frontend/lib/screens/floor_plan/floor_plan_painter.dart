import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/floor_plan.dart';

/// Định dạng mét kiểu Việt Nam: 4.09 -> "4,09".
String formatMeters(double v) => v.toStringAsFixed(2).replaceAll('.', ',');

/// Màu dùng để vẽ — truyền từ palette của theme hiện tại (sáng/tối).
@immutable
class FloorPlanColors {
  final Color background;
  final Color wall;
  final Color grid;
  final Color label;
  final Color subLabel;
  final Color door;
  final Color editAccent;
  final List<Color> roomFills;

  const FloorPlanColors({
    required this.background,
    required this.wall,
    required this.grid,
    required this.label,
    required this.subLabel,
    required this.door,
    required this.editAccent,
    required this.roomFills,
  });

  @override
  bool operator ==(Object other) =>
      other is FloorPlanColors &&
      other.background == background &&
      other.wall == wall &&
      other.grid == grid &&
      other.label == label &&
      other.subLabel == subLabel &&
      other.door == door &&
      other.editAccent == editAccent &&
      _listEq(other.roomFills, roomFills);

  @override
  int get hashCode => Object.hash(background, wall, grid, label, subLabel, door, editAccent, Object.hashAll(roomFills));
}

bool _listEq<T>(List<T> a, List<T> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

/// Vẽ phần TĨNH của sơ đồ: nền phòng, lưới 1 m, tường, cửa, nhãn tên + kích thước.
///
/// KHÔNG vẽ thiết bị — thiết bị là widget riêng (mỗi cái tự lắng nghe trạng
/// thái của mình), nên đổi trạng thái 1 thiết bị không vẽ lại sơ đồ.
/// `shouldRepaint` so `identical` danh sách phòng/cửa: kéo thiết bị trong chế
/// độ sửa cũng không vẽ lại tường.
class FloorPlanPainter extends CustomPainter {
  final List<PlanRoom> rooms;
  final List<PlanDoor> doors;
  final PlanGeometry geometry;
  final FloorPlanColors colors;
  final bool editing;

  FloorPlanPainter({
    required this.rooms,
    required this.doors,
    required this.geometry,
    required this.colors,
    this.editing = false,
  });

  /// Độ dày tường hiển thị (≈10 cm thật, kẹp để luôn nhìn thấy được).
  double get wallPx => (0.10 * geometry.pxPerMeter).clamp(3.0, 9.0);

  @override
  void paint(Canvas canvas, Size size) {
    for (var i = 0; i < rooms.length; i++) {
      _paintRoom(canvas, rooms[i], colors.roomFills[i % colors.roomFills.length]);
    }
    final byId = {for (final r in rooms) r.id: r};
    for (final d in doors) {
      final r = byId[d.roomId];
      if (r != null) _paintDoor(canvas, d, r);
    }
    for (final r in rooms) {
      _paintLabels(canvas, r);
    }
  }

  void _paintRoom(Canvas canvas, PlanRoom r, Color fill) {
    final rect = geometry.rectToPx(r.rect);
    canvas.drawRect(rect, Paint()..color = fill);

    // Lưới 1 m giúp ước lượng khoảng cách thật khi đặt thiết bị.
    final grid = Paint()
      ..color = colors.grid
      ..strokeWidth = 1;
    for (var m = 1.0; m < r.width - 0.01; m += 1) {
      final x = rect.left + m * geometry.pxPerMeter;
      canvas.drawLine(Offset(x, rect.top), Offset(x, rect.bottom), grid);
    }
    for (var m = 1.0; m < r.depth - 0.01; m += 1) {
      final y = rect.top + m * geometry.pxPerMeter;
      canvas.drawLine(Offset(rect.left, y), Offset(rect.right, y), grid);
    }

    canvas.drawRect(
      rect,
      Paint()
        ..color = editing ? colors.editAccent : colors.wall
        ..style = PaintingStyle.stroke
        ..strokeWidth = wallPx
        ..strokeJoin = StrokeJoin.miter,
    );
  }

  /// Cửa = khe hở trên tường + 2 vạch ở 2 mép khe + 1 đường mảnh màu cửa.
  /// Không vẽ cánh/chiều mở: hướng mở là dữ liệu chưa có, không đoán.
  void _paintDoor(Canvas canvas, PlanDoor d, PlanRoom r) {
    final (a, b) = d.endpoints(r);
    final pa = geometry.toPx(a);
    final pb = geometry.toPx(b);
    final w = wallPx;
    // Xóa đoạn tường ở khe cửa.
    canvas.drawLine(
      pa,
      pb,
      Paint()
        ..color = colors.background
        ..strokeWidth = w + 2
        ..strokeCap = StrokeCap.butt,
    );
    final horizontal = d.wall == Wall.top || d.wall == Wall.bottom;
    final n = horizontal ? Offset(0, w * 1.2) : Offset(w * 1.2, 0);
    final jamb = Paint()
      ..color = colors.wall
      ..strokeWidth = math.max(2, w / 2);
    canvas.drawLine(pa - n, pa + n, jamb);
    canvas.drawLine(pb - n, pb + n, jamb);
    canvas.drawLine(
      pa,
      pb,
      Paint()
        ..color = editing ? colors.editAccent : colors.door
        ..strokeWidth = editing ? 4 : 2,
    );
  }

  void _paintLabels(Canvas canvas, PlanRoom r) {
    final rect = geometry.rectToPx(r.rect);
    final ppm = geometry.pxPerMeter;
    final nameSize = (ppm * 0.22).clamp(10.0, 15.0);
    final tp = TextPainter(
      text: TextSpan(children: [
        TextSpan(
          text: '${r.name}\n',
          style: TextStyle(color: colors.label, fontSize: nameSize, fontWeight: FontWeight.w700),
        ),
        TextSpan(
          text: '${formatMeters(r.width)} × ${formatMeters(r.depth)} m',
          style: TextStyle(color: colors.subLabel, fontSize: nameSize * 0.8),
        ),
      ]),
      textAlign: TextAlign.center,
      textDirection: TextDirection.ltr,
      maxLines: 2,
      ellipsis: '…',
    )..layout(maxWidth: math.max(0, rect.width - wallPx * 2 - 4));
    // Góc trên của phòng — thiết bị thường đặt quanh giữa phòng.
    tp.paint(canvas, Offset(rect.center.dx - tp.width / 2, rect.top + wallPx + 4));
  }

  @override
  bool shouldRepaint(covariant FloorPlanPainter old) =>
      !identical(old.rooms, rooms) ||
      !identical(old.doors, doors) ||
      old.geometry != geometry ||
      old.colors != colors ||
      old.editing != editing;
}
