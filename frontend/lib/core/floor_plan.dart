import 'dart:convert';
import 'dart:math' as math;
import 'dart:ui' show Offset, Rect, Size;

import 'package:http/http.dart' as http;

import 'auth_service.dart';
import 'config.dart';

/// Sơ đồ mặt bằng 2D — model + hình học thuần (không Flutter widget) để test
/// được. Khớp backend `services/floor_plan.py`.
///
/// ĐƠN VỊ LÀ MÉT. Trục x sang phải, y xuống dưới.
/// - Phòng: kích thước thật + vị trí góc trên-trái trên sơ đồ.
/// - Cửa: tường nào của phòng nào, cách đầu tường bao nhiêu mét, rộng bao nhiêu.
/// - Thiết bị: tọa độ mét TÍNH TỪ góc trên-trái của phòng chứa nó ⇒ không phụ
///   thuộc kích thước màn hình / zoom; di chuyển phòng thì thiết bị đi theo.
enum Wall { top, bottom, left, right }

const Map<Wall, String> wallLabels = {
  Wall.top: 'Tường trên',
  Wall.bottom: 'Tường dưới',
  Wall.left: 'Tường trái',
  Wall.right: 'Tường phải',
};

double _d(dynamic v, [double fallback = 0]) => v is num && v.isFinite ? v.toDouble() : fallback;

/// Làm tròn mm — khớp backend (round 3) để lưu xong đọc lại không lệch.
double _mm(double v) => (v * 1000).roundToDouble() / 1000;

class PlanRoom {
  final String id;
  final String name;
  final double width; // m, theo trục x
  final double depth; // m, theo trục y
  final double x;
  final double y;

  const PlanRoom({
    required this.id,
    required this.name,
    required this.width,
    required this.depth,
    this.x = 0,
    this.y = 0,
  });

  Rect get rect => Rect.fromLTWH(x, y, width, depth);

  double wallLength(Wall wall) => (wall == Wall.top || wall == Wall.bottom) ? width : depth;

  PlanRoom copyWith({String? name, double? width, double? depth, double? x, double? y}) => PlanRoom(
        id: id,
        name: name ?? this.name,
        width: width ?? this.width,
        depth: depth ?? this.depth,
        x: x ?? this.x,
        y: y ?? this.y,
      );

  factory PlanRoom.fromJson(Map<String, dynamic> j) => PlanRoom(
        id: '${j['id']}',
        name: '${j['name'] ?? ''}',
        width: _d(j['width'], 1),
        depth: _d(j['depth'], 1),
        x: _d(j['x']),
        y: _d(j['y']),
      );

  Map<String, dynamic> toJson() =>
      {'id': id, 'name': name, 'width': width, 'depth': depth, 'x': _mm(x), 'y': _mm(y)};
}

class PlanDoor {
  final String id;
  final String roomId;
  final Wall wall;
  final double offset; // m từ đầu tường (trái với trên/dưới, trên với trái/phải)
  final double width;

  const PlanDoor({
    required this.id,
    required this.roomId,
    required this.wall,
    required this.offset,
    required this.width,
  });

  PlanDoor copyWith({double? offset, double? width}) => PlanDoor(
        id: id,
        roomId: roomId,
        wall: wall,
        offset: offset ?? this.offset,
        width: width ?? this.width,
      );

  /// 2 đầu khe cửa, tọa độ mét tuyệt đối trên sơ đồ.
  (Offset, Offset) endpoints(PlanRoom r) {
    switch (wall) {
      case Wall.top:
        return (Offset(r.x + offset, r.y), Offset(r.x + offset + width, r.y));
      case Wall.bottom:
        return (Offset(r.x + offset, r.y + r.depth), Offset(r.x + offset + width, r.y + r.depth));
      case Wall.left:
        return (Offset(r.x, r.y + offset), Offset(r.x, r.y + offset + width));
      case Wall.right:
        return (Offset(r.x + r.width, r.y + offset), Offset(r.x + r.width, r.y + offset + width));
    }
  }

  factory PlanDoor.fromJson(Map<String, dynamic> j) => PlanDoor(
        id: '${j['id']}',
        roomId: '${j['room']}',
        wall: Wall.values.firstWhere((w) => w.name == j['wall'], orElse: () => Wall.bottom),
        offset: _d(j['offset']),
        width: _d(j['width'], 0.8),
      );

  Map<String, dynamic> toJson() =>
      {'id': id, 'room': roomId, 'wall': wall.name, 'offset': _mm(offset), 'width': _mm(width)};
}

class DevicePlacement {
  final String deviceId;
  final String roomId;
  final double x; // m tính từ góc trên-trái của phòng
  final double y;

  const DevicePlacement({required this.deviceId, required this.roomId, required this.x, required this.y});

  factory DevicePlacement.fromJson(Map<String, dynamic> j) => DevicePlacement(
        deviceId: '${j['device_id']}',
        roomId: '${j['room']}',
        x: _d(j['x']),
        y: _d(j['y']),
      );

  Map<String, dynamic> toJson() => {'device_id': deviceId, 'room': roomId, 'x': _mm(x), 'y': _mm(y)};
}

/// Sơ đồ bất biến: mọi thao tác sửa trả bản MỚI.
///
/// Thao tác chỉ đụng thiết bị thì GIỮ NGUYÊN instance `rooms`/`doors` ⇒ phần
/// vẽ tường/phòng (so sánh `identical`) không phải vẽ lại khi kéo thiết bị.
class FloorPlan {
  final List<PlanRoom> rooms;
  final List<PlanDoor> doors;
  final List<DevicePlacement> devices;

  /// false = chủ nhà chưa từng lưu: đang là bố cục mặc định từ backend.
  final bool configured;

  const FloorPlan({required this.rooms, this.doors = const [], this.devices = const [], this.configured = false});

  /// Lưới hút khi kéo phòng (5 cm) và khoảng hút mép phòng khác (20 cm).
  static const double gridStep = 0.05;
  static const double edgeSnap = 0.20;

  factory FloorPlan.fromJson(Map<String, dynamic> j) {
    List<Map<String, dynamic>> list(String k) =>
        (j[k] is List ? j[k] as List : const []).whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    return FloorPlan(
      rooms: list('rooms').map(PlanRoom.fromJson).toList(growable: false),
      doors: list('doors').map(PlanDoor.fromJson).toList(growable: false),
      devices: list('devices').map(DevicePlacement.fromJson).toList(growable: false),
      configured: j['configured'] == true,
    );
  }

  Map<String, dynamic> toJson() => {
        'rooms': [for (final r in rooms) r.toJson()],
        'doors': [for (final d in doors) d.toJson()],
        'devices': [for (final p in devices) p.toJson()],
      };

  PlanRoom? room(String id) {
    for (final r in rooms) {
      if (r.id == id) return r;
    }
    return null;
  }

  DevicePlacement? placement(String deviceId) {
    for (final p in devices) {
      if (p.deviceId == deviceId) return p;
    }
    return null;
  }

  /// Tâm thiết bị theo mét TUYỆT ĐỐI trên sơ đồ (null = chưa đặt / phòng mất).
  Offset? deviceCenter(String deviceId) {
    final p = placement(deviceId);
    if (p == null) return null;
    final r = room(p.roomId);
    if (r == null) return null;
    return Offset(r.x + p.x, r.y + p.y);
  }

  /// Khung bao mọi phòng (mét).
  Rect get bounds {
    if (rooms.isEmpty) return const Rect.fromLTWH(0, 0, 1, 1);
    var b = rooms.first.rect;
    for (final r in rooms.skip(1)) {
      b = b.expandToInclude(r.rect);
    }
    return b;
  }

  /// Phòng chứa điểm (mét tuyệt đối); điểm ngoài mọi phòng -> phòng gần nhất.
  PlanRoom roomAt(Offset p) {
    PlanRoom best = rooms.first;
    var bestDist = double.infinity;
    for (final r in rooms) {
      final rect = r.rect;
      if (rect.contains(p)) return r;
      final dx = math.max(0.0, math.max(rect.left - p.dx, p.dx - rect.right));
      final dy = math.max(0.0, math.max(rect.top - p.dy, p.dy - rect.bottom));
      final dist = dx * dx + dy * dy;
      if (dist < bestDist) {
        bestDist = dist;
        best = r;
      }
    }
    return best;
  }

  FloorPlan _with({List<PlanRoom>? rooms, List<PlanDoor>? doors, List<DevicePlacement>? devices}) => FloorPlan(
        rooms: rooms ?? this.rooms,
        doors: doors ?? this.doors,
        devices: devices ?? this.devices,
        configured: configured,
      );

  // ------------------------------------------------------------ thiết bị
  /// Đặt/di chuyển thiết bị tới điểm `abs` (mét tuyệt đối): tự nhận phòng chứa
  /// điểm đó, kẹp vào trong phòng — thiết bị không bao giờ nằm ngoài phòng.
  FloorPlan moveDevice(String deviceId, Offset abs) {
    final r = roomAt(abs);
    final placed = DevicePlacement(
      deviceId: deviceId,
      roomId: r.id,
      x: (abs.dx - r.x).clamp(0.0, r.width),
      y: (abs.dy - r.y).clamp(0.0, r.depth),
    );
    final i = devices.indexWhere((p) => p.deviceId == deviceId);
    final next = List<DevicePlacement>.of(devices);
    if (i < 0) {
      next.add(placed);
    } else {
      next[i] = placed;
    }
    return _with(devices: List.unmodifiable(next));
  }

  /// Đặt thiết bị chưa có vị trí vào giữa phòng (lệch dần để không chồng nhau).
  FloorPlan placeDevice(String deviceId, String roomId) {
    final r = room(roomId) ?? rooms.first;
    final already = devices.where((p) => p.roomId == r.id).length;
    final shift = (already % 5 - 2) * 0.3;
    return moveDevice(deviceId, r.rect.center + Offset(shift, shift / 2));
  }

  FloorPlan removeDevice(String deviceId) =>
      _with(devices: List.unmodifiable(devices.where((p) => p.deviceId != deviceId)));

  // ------------------------------------------------------------ phòng
  /// Di chuyển phòng tới góc trên-trái `topLeft`, hút lưới 5 cm + hút sát mép
  /// phòng khác (để 2 phòng chung tường khít nhau, không hở/chồng vài cm).
  FloorPlan moveRoom(String roomId, Offset topLeft) {
    final r = room(roomId);
    if (r == null) return this;
    double snap(double v) => (v / gridStep).roundToDouble() * gridStep;
    var x = snap(topLeft.dx);
    var y = snap(topLeft.dy);
    var bestX = edgeSnap, bestY = edgeSnap;
    for (final o in rooms) {
      if (o.id == roomId) continue;
      // Mép trái/phải của phòng này so với mép trái/phải phòng kia.
      for (final (mine, theirs) in [
        (topLeft.dx, o.x), (topLeft.dx, o.x + o.width),
        (topLeft.dx + r.width, o.x), (topLeft.dx + r.width, o.x + o.width),
      ]) {
        final dist = (mine - theirs).abs();
        if (dist < bestX) {
          bestX = dist;
          x = topLeft.dx + (theirs - mine);
        }
      }
      for (final (mine, theirs) in [
        (topLeft.dy, o.y), (topLeft.dy, o.y + o.depth),
        (topLeft.dy + r.depth, o.y), (topLeft.dy + r.depth, o.y + o.depth),
      ]) {
        final dist = (mine - theirs).abs();
        if (dist < bestY) {
          bestY = dist;
          y = topLeft.dy + (theirs - mine);
        }
      }
    }
    return _with(rooms: List.unmodifiable([
      for (final o in rooms) o.id == roomId ? o.copyWith(x: _mm(x), y: _mm(y)) : o,
    ]));
  }

  /// Đổi kích thước phòng; cửa + thiết bị được kẹp lại vào phòng mới (cửa rộng
  /// hơn tường mới thì thu hẹp bằng tường — không âm thầm xóa cửa).
  FloorPlan resizeRoom(String roomId, {required double width, required double depth}) {
    final r = room(roomId);
    if (r == null) return this;
    final nr = r.copyWith(width: width, depth: depth);
    PlanDoor fit(PlanDoor d) {
      final len = nr.wallLength(d.wall);
      final w = math.min(d.width, len);
      return d.copyWith(width: w, offset: d.offset.clamp(0.0, len - w));
    }

    return _with(
      rooms: List.unmodifiable([for (final o in rooms) o.id == roomId ? nr : o]),
      doors: List.unmodifiable([for (final d in doors) d.roomId == roomId ? fit(d) : d]),
      devices: List.unmodifiable([
        for (final p in devices)
          p.roomId == roomId
              ? DevicePlacement(deviceId: p.deviceId, roomId: p.roomId,
                  x: p.x.clamp(0.0, width), y: p.y.clamp(0.0, depth))
              : p,
      ]),
    );
  }

  // ------------------------------------------------------------ cửa
  static const double defaultDoorWidth = 0.8;

  /// Thêm cửa vào giữa 1 bức tường. Tường ngắn hơn cửa mặc định thì cửa = cả tường.
  FloorPlan addDoor(String roomId, Wall wall, {String? id}) {
    final r = room(roomId);
    if (r == null) return this;
    final len = r.wallLength(wall);
    final w = math.min(defaultDoorWidth, len);
    var n = doors.length + 1;
    String newId = id ?? 'door$n';
    while (doors.any((d) => d.id == newId)) {
      newId = 'door${++n}';
    }
    return _with(doors: List.unmodifiable([
      ...doors,
      PlanDoor(id: newId, roomId: roomId, wall: wall, offset: _mm((len - w) / 2), width: w),
    ]));
  }

  /// Trượt cửa dọc tường sao cho TÂM cửa gần điểm `abs` nhất.
  FloorPlan slideDoor(String doorId, Offset abs) {
    final i = doors.indexWhere((d) => d.id == doorId);
    if (i < 0) return this;
    final d = doors[i];
    final r = room(d.roomId);
    if (r == null) return this;
    final along = (d.wall == Wall.top || d.wall == Wall.bottom) ? abs.dx - r.x : abs.dy - r.y;
    final offset = (along - d.width / 2).clamp(0.0, r.wallLength(d.wall) - d.width);
    final next = List<PlanDoor>.of(doors)..[i] = d.copyWith(offset: _mm(offset));
    return _with(doors: List.unmodifiable(next));
  }

  /// Đổi bề rộng cửa, giữ nguyên TÂM cửa nếu còn vừa tường (không thì kẹp vào tường).
  FloorPlan resizeDoor(String doorId, double width) {
    final i = doors.indexWhere((d) => d.id == doorId);
    if (i < 0) return this;
    final d = doors[i];
    final r = room(d.roomId);
    if (r == null) return this;
    final len = r.wallLength(d.wall);
    final w = width.clamp(0.3, len);
    final center = d.offset + d.width / 2;
    final offset = (center - w / 2).clamp(0.0, len - w);
    final next = List<PlanDoor>.of(doors)..[i] = d.copyWith(offset: _mm(offset), width: _mm(w));
    return _with(doors: List.unmodifiable(next));
  }

  FloorPlan removeDoor(String doorId) => _with(doors: List.unmodifiable(doors.where((d) => d.id != doorId)));
}

/// Quy đổi mét <-> pixel cho 1 lần vẽ. Vị trí mọi thứ (phòng, cửa, icon) đi
/// qua ĐÚNG MỘT hệ số `pxPerMeter` ⇒ 2 phòng luôn cùng tỷ lệ; zoom/pan do
/// InteractiveViewer biến đổi CẢ lớp vẽ lẫn lớp icon nên không lệch nhau.
class PlanGeometry {
  /// Vùng sơ đồ (mét) được vẽ, đã cộng lề cho nhãn kích thước.
  final Rect viewMeters;
  final double pxPerMeter;

  const PlanGeometry(this.viewMeters, this.pxPerMeter);

  /// Lề quanh sơ đồ (mét) để có chỗ cho nhãn kích thước ngoài tường.
  static const double margin = 0.6;

  /// Tỷ lệ vừa khít `available` (giữ tỷ lệ — không bao giờ kéo giãn 1 trục).
  factory PlanGeometry.fit(FloorPlan plan, Size available) {
    final view = plan.bounds.inflate(margin);
    final ppm = math.min(available.width / view.width, available.height / view.height);
    return PlanGeometry(view, ppm.isFinite && ppm > 0 ? ppm : 1);
  }

  Size get size => Size(viewMeters.width * pxPerMeter, viewMeters.height * pxPerMeter);

  Offset toPx(Offset meters) => (meters - viewMeters.topLeft) * pxPerMeter;

  Offset toMeters(Offset px) => px / pxPerMeter + viewMeters.topLeft;

  Rect rectToPx(Rect meters) => Rect.fromPoints(toPx(meters.topLeft), toPx(meters.bottomRight));

  @override
  bool operator ==(Object other) =>
      other is PlanGeometry && other.viewMeters == viewMeters && other.pxPerMeter == pxPerMeter;

  @override
  int get hashCode => Object.hash(viewMeters, pxPerMeter);
}

/// Đọc / lưu sơ đồ (`/api/floor-plan`).
class FloorPlanApi {
  FloorPlanApi._();

  static const String _base = AppConfig.baseUrl;

  static Future<Map<String, String>> _headers({bool jsonBody = false}) async {
    try {
      return await AuthService.headers(jsonBody: jsonBody);
    } on NotAuthenticatedException {
      return jsonBody ? const {'Content-Type': 'application/json'} : const {};
    }
  }

  static (FloorPlan?, String?) _parse(http.Response res) {
    if (res.statusCode == 401) {
      AuthService.handleUnauthorized();
      return (null, 'Phiên đăng nhập đã hết hạn.');
    }
    try {
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body is Map && body['status'] == 'success') {
        return (FloorPlan.fromJson(Map<String, dynamic>.from(body['data'] as Map)), null);
      }
      final msg = body is Map ? (body['detail'] ?? body['message']) : null;
      return (null, msg is String ? msg : 'Lỗi máy chủ (HTTP ${res.statusCode})');
    } catch (_) {
      return (null, 'Phản hồi không đọc được từ máy chủ.');
    }
  }

  static Future<(FloorPlan?, String?)> fetch() async {
    try {
      final res = await http
          .get(Uri.parse('$_base/api/floor-plan'), headers: await _headers())
          .timeout(AppConfig.apiTimeout);
      return _parse(res);
    } catch (_) {
      return (null, 'Mất kết nối máy chủ.');
    }
  }

  static Future<(FloorPlan?, String?)> save(FloorPlan plan) async {
    try {
      final res = await http
          .put(Uri.parse('$_base/api/floor-plan'),
              headers: await _headers(jsonBody: true), body: json.encode(plan.toJson()))
          .timeout(AppConfig.apiTimeout);
      return _parse(res);
    } catch (_) {
      return (null, 'Mất kết nối máy chủ.');
    }
  }
}
