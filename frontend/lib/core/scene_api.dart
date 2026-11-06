import 'dart:convert';
import 'package:http/http.dart' as http;

import 'auth_service.dart';
import 'config.dart';

/// 1 hành động trong kịch bản (đã chuẩn hóa phía backend theo loại thiết bị).
class SceneAction {
  final String deviceId;
  final String actionType;   // on | off | mode
  final String? actionValue;

  const SceneAction(this.deviceId, this.actionType, [this.actionValue]);

  factory SceneAction.fromJson(Map<String, dynamic> j) =>
      SceneAction('${j['device_id']}', '${j['action_type']}', j['action_value']?.toString());

  Map<String, dynamic> toJson() =>
      {'device_id': deviceId, 'action_type': actionType, 'action_value': actionValue};
}

/// 1 điều kiện chạy kịch bản — khớp backend services/scene_condition_engine.py.
/// Giữ nguyên map gốc ([data]) để loại điều kiện app chưa biết (bản backend mới
/// hơn) vẫn được gửi lại nguyên vẹn khi lưu, không bị xóa âm thầm.
class SceneCondition {
  static const timeRange = 'time_range';
  static const deviceState = 'device_state';
  static const defaultTimezone = 'Asia/Ho_Chi_Minh';

  final String type;
  final Map<String, dynamic> data;

  const SceneCondition._(this.type, this.data);

  /// Khoảng giờ [start, end) dạng HH:MM; start > end = qua đêm.
  factory SceneCondition.time(String start, String end) =>
      SceneCondition._(timeRange, {'start': start, 'end': end, 'timezone': defaultTimezone});

  /// Thiết bị [deviceId] phải đang ở [expected] (on | off | open | closed).
  factory SceneCondition.device(String deviceId, String expected) =>
      SceneCondition._(deviceState, {'device_id': deviceId, 'expected_state': expected});

  factory SceneCondition.fromJson(Map<String, dynamic> j) {
    final data = Map<String, dynamic>.from(j)..remove('type');
    return SceneCondition._('${j['type'] ?? ''}', data);
  }

  Map<String, dynamic> toJson() => {'type': type, ...data};

  String? get start => data['start']?.toString();
  String? get end => data['end']?.toString();
  String? get deviceId => data['device_id']?.toString();
  String? get expectedState => data['expected_state']?.toString();

  /// Khoảng giờ vắt qua nửa đêm (22:00 → 06:00).
  bool get isOvernight => type == timeRange && (start ?? '').compareTo(end ?? '') > 0;
}

/// Bộ điều kiện + cách kết hợp: AND = tất cả đúng, OR = chỉ cần 1 đúng.
class SceneConditions {
  final String operator;
  final List<SceneCondition> items;

  const SceneConditions({this.operator = 'AND', this.items = const []});

  static const none = SceneConditions();

  bool get isEmpty => items.isEmpty;

  /// Backend cũ không trả `conditions` -> không điều kiện.
  factory SceneConditions.fromJson(Object? j) {
    if (j is! Map) return none;
    final op = '${j['operator'] ?? 'AND'}'.toUpperCase();
    return SceneConditions(
      operator: op == 'OR' ? 'OR' : 'AND',
      items: ((j['items'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => SceneCondition.fromJson(Map<String, dynamic>.from(e)))
          .toList(),
    );
  }

  Map<String, dynamic> toJson() => {'operator': operator, 'items': [for (final c in items) c.toJson()]};
}

/// Kịch bản: 1 nút chạy nhiều hành động (khớp bảng `scenes`).
class Scene {
  final int id;
  final String name;
  final String? icon;
  final List<SceneAction> actions;
  final SceneConditions conditions;

  const Scene({
    required this.id,
    required this.name,
    this.icon,
    required this.actions,
    this.conditions = SceneConditions.none,
  });

  factory Scene.fromJson(Map<String, dynamic> j) => Scene(
        id: (j['id'] as num).toInt(),
        name: '${j['name'] ?? ''}',
        icon: j['icon'] as String?,
        actions: ((j['actions'] as List?) ?? [])
            .map((e) => SceneAction.fromJson(Map<String, dynamic>.from(e as Map)))
            .toList(),
        conditions: SceneConditions.fromJson(j['conditions']),
      );
}

/// Kết quả chạy kịch bản: từng hành động + số hành động bị bỏ qua (ngoài khu),
/// hoặc cả kịch bản bị bỏ qua vì điều kiện không đạt ([blockedMessage]).
class SceneRunResult {
  final int ok;
  final int failed;
  final int skipped;
  final String? blockedMessage; // "Kịch bản đã bỏ qua: ..." — không lệnh nào được gửi
  final String? blockedReason;  // lý do chi tiết từ backend, vd "Máy bơm đang bật (cần đang tắt)"

  const SceneRunResult(this.ok, this.failed, this.skipped, {this.blockedMessage, this.blockedReason});

  bool get conditionsBlocked => blockedMessage != null;

  /// Đọc body của POST /api/scenes/{id}/run (status success | skipped).
  factory SceneRunResult.fromResponse(Map<String, dynamic> body) {
    final data = body['data'] is Map ? Map<String, dynamic>.from(body['data'] as Map) : <String, dynamic>{};
    if (body['status'] == 'skipped') {
      final reason = (data['conditions'] as Map?)?['reason']?.toString();
      return SceneRunResult(0, 0, 0,
          blockedMessage: '${body['message'] ?? 'Kịch bản đã bỏ qua: Không thỏa mãn điều kiện thực thi.'}',
          blockedReason: (reason == null || reason.isEmpty) ? null : reason);
    }
    final results = ((data['results'] as List?) ?? []).whereType<Map>();
    final ok = results.where((r) => r['success'] == true).length;
    return SceneRunResult(ok, results.length - ok, (data['skipped'] as num?)?.toInt() ?? 0);
  }

  String get summary {
    if (conditionsBlocked) {
      return blockedReason == null ? blockedMessage! : '$blockedMessage\n$blockedReason';
    }
    final parts = <String>[if (ok > 0) '$ok xong', if (failed > 0) '$failed lỗi', if (skipped > 0) '$skipped bỏ qua (ngoài khu)'];
    return parts.isEmpty ? 'Không có hành động nào' : parts.join(' • ');
  }
}

class SceneApi {
  static const String _base = '${AppConfig.baseUrl}/api/scenes';

  static Future<Map<String, String>> _headers({bool jsonBody = false}) async {
    try {
      return await AuthService.headers(jsonBody: jsonBody);
    } on NotAuthenticatedException {
      return jsonBody ? const {'Content-Type': 'application/json'} : const {};
    }
  }

  static Future<List<Scene>?> fetchScenes() async {
    try {
      final res = await http.get(Uri.parse(_base), headers: await _headers()).timeout(AppConfig.apiTimeout);
      if (res.statusCode == 401) AuthService.handleUnauthorized();
      if (res.statusCode != 200) return null;
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (body['status'] != 'success') return null;
      return ((body['data'] as List?) ?? [])
          .map((e) => Scene.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    } catch (_) {
      return null;
    }
  }

  /// Tạo ([id] null) hoặc sửa kịch bản. Trả lỗi tiếng Việt hoặc null nếu thành công.
  /// Luôn gửi `conditions` (kể cả rỗng) để sửa kịch bản xóa được điều kiện cũ.
  static Future<String?> save({
    int? id,
    required String name,
    String? icon,
    required List<SceneAction> actions,
    SceneConditions conditions = SceneConditions.none,
  }) async {
    final headers = await _headers(jsonBody: true);
    final body = json.encode({
      'name': name,
      'icon': icon,
      'actions': [for (final a in actions) a.toJson()],
      'conditions': conditions.toJson(),
    });
    final (_, err) = await _send(() => id == null
        ? http.post(Uri.parse(_base), headers: headers, body: body)
        : http.patch(Uri.parse('$_base/$id'), headers: headers, body: body));
    return err;
  }

  static Future<String?> delete(int id) async {
    final headers = await _headers();
    final (_, err) = await _send(() => http.delete(Uri.parse('$_base/$id'), headers: headers));
    return err;
  }

  /// Chạy kịch bản. Trả (kết quả, lỗi) — đúng 1 trong 2 khác null.
  static Future<(SceneRunResult?, String?)> run(int id) async {
    final headers = await _headers();
    // "skipped" = điều kiện không đạt: không phải lỗi, không lệnh nào được gửi.
    final (body, err) = await _send(
      () => http.post(Uri.parse('$_base/$id/run'), headers: headers),
      timeout: const Duration(seconds: 40), // đọc điều kiện + nhiều lệnh IoT tuần tự
      okStatuses: const {'success', 'skipped'},
    );
    if (err != null) return (null, err);
    return (SceneRunResult.fromResponse(body!), null);
  }

  /// Gửi request; trả (body, null) nếu `status` thuộc [okStatuses], (null, thông
  /// báo lỗi) nếu không. FastAPI để lỗi ở `detail`, endpoint cũ ở `message`.
  static Future<(Map<String, dynamic>?, String?)> _send(Future<http.Response> Function() request,
      {Duration? timeout, Set<String> okStatuses = const {'success'}}) async {
    try {
      final res = await request().timeout(timeout ?? AppConfig.apiTimeout);
      if (res.statusCode == 401) {
        AuthService.handleUnauthorized();
        return (null, 'Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.');
      }
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body is Map && okStatuses.contains(body['status'])) {
        return (Map<String, dynamic>.from(body), null);
      }
      return (null, '${body['detail'] ?? body['message'] ?? 'Lỗi máy chủ (HTTP ${res.statusCode})'}');
    } catch (_) {
      return (null, 'Mất kết nối máy chủ. Thử lại sau.');
    }
  }
}
