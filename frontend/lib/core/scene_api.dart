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

/// Kịch bản: 1 nút chạy nhiều hành động (khớp bảng `scenes`).
class Scene {
  final int id;
  final String name;
  final String? icon;
  final List<SceneAction> actions;

  const Scene({required this.id, required this.name, this.icon, required this.actions});

  factory Scene.fromJson(Map<String, dynamic> j) => Scene(
        id: (j['id'] as num).toInt(),
        name: '${j['name'] ?? ''}',
        icon: j['icon'] as String?,
        actions: ((j['actions'] as List?) ?? [])
            .map((e) => SceneAction.fromJson(Map<String, dynamic>.from(e as Map)))
            .toList(),
      );
}

/// Kết quả chạy kịch bản: từng hành động + số hành động bị bỏ qua (ngoài khu).
class SceneRunResult {
  final int ok;
  final int failed;
  final int skipped;
  const SceneRunResult(this.ok, this.failed, this.skipped);

  String get summary {
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
  static Future<String?> save({int? id, required String name, String? icon, required List<SceneAction> actions}) async {
    final headers = await _headers(jsonBody: true);
    final body = json.encode({'name': name, 'icon': icon, 'actions': [for (final a in actions) a.toJson()]});
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
    final (data, err) = await _send(
      () => http.post(Uri.parse('$_base/$id/run'), headers: headers),
      timeout: const Duration(seconds: 40), // nhiều lệnh IoT tuần tự
    );
    if (err != null) return (null, err);
    final results = ((data?['results'] as List?) ?? []).cast<Map>();
    final ok = results.where((r) => r['success'] == true).length;
    return (SceneRunResult(ok, results.length - ok, (data?['skipped'] as num?)?.toInt() ?? 0), null);
  }

  /// Gửi request; trả (data, null) nếu success, (null, thông báo lỗi) nếu không.
  /// FastAPI để lỗi ở `detail`, endpoint cũ ở `message`.
  static Future<(Map<String, dynamic>?, String?)> _send(Future<http.Response> Function() request,
      {Duration? timeout}) async {
    try {
      final res = await request().timeout(timeout ?? AppConfig.apiTimeout);
      if (res.statusCode == 401) {
        AuthService.handleUnauthorized();
        return (null, 'Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.');
      }
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body['status'] == 'success') {
        final data = body['data'];
        return (data is Map ? Map<String, dynamic>.from(data) : <String, dynamic>{}, null);
      }
      return (null, '${body['detail'] ?? body['message'] ?? 'Lỗi máy chủ (HTTP ${res.statusCode})'}');
    } catch (_) {
      return (null, 'Mất kết nối máy chủ. Thử lại sau.');
    }
  }
}
