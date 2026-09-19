import 'dart:convert';

import 'package:http/http.dart' as http;

import 'auth_service.dart';
import 'config.dart';

/// Một khu vực trong nhà.
class Zone {
  final int id;
  final String name;
  final int sortOrder;

  const Zone({required this.id, required this.name, required this.sortOrder});

  factory Zone.fromJson(Map<String, dynamic> j) => Zone(
        id: j['id'] as int,
        name: '${j['name'] ?? ''}',
        sortOrder: (j['sort_order'] ?? 0) as int,
      );
}

/// Một thành viên trong nhà.
class Member {
  final String userId;
  final String email;
  final String displayName;
  final String role;   // owner | adult | kid | guest
  final String status; // pending | active | blocked
  final List<int> zoneIds;

  const Member({
    required this.userId,
    required this.email,
    required this.displayName,
    required this.role,
    required this.status,
    required this.zoneIds,
  });

  bool get isPending => status == 'pending';
  bool get isOwner => role == 'owner';

  /// owner/adult thấy mọi khu theo luật vai — grant theo khu không áp dụng,
  /// nên UI phải ẩn phần tick khu cho hai vai này, tránh hiểu nhầm là cấp thiếu.
  bool get seesAllZones => role == 'owner' || role == 'adult';

  factory Member.fromJson(Map<String, dynamic> j) => Member(
        userId: '${j['user_id'] ?? ''}',
        email: '${j['email'] ?? ''}',
        displayName: '${j['display_name'] ?? ''}',
        role: '${j['role'] ?? 'guest'}',
        status: '${j['status'] ?? 'pending'}',
        zoneIds: ((j['zone_ids'] as List?) ?? []).map((e) => e as int).toList(),
      );
}

/// Gọi các endpoint quản trị nhà: khu vực, thành viên, gán thiết bị vào khu.
class HouseholdApi {
  HouseholdApi._();

  static const String _base = AppConfig.baseUrl;

  static Future<Map<String, String>> _headers({bool jsonBody = false}) async {
    try {
      return await AuthService.headers(jsonBody: jsonBody);
    } on NotAuthenticatedException {
      return jsonBody ? const {'Content-Type': 'application/json'} : const {};
    }
  }

  /// Đọc {status, data} -> data, hoặc null nếu lỗi.
  static dynamic _data(http.Response res) {
    if (res.statusCode == 401) {
      AuthService.handleUnauthorized();
      return null;
    }
    if (res.statusCode != 200) return null;
    final body = json.decode(utf8.decode(res.bodyBytes));
    if (body['status'] != 'success') return null;
    return body['data'];
  }

  /// Trả thông báo lỗi tiếng Việt, hoặc null nếu thành công.
  /// FastAPI đặt lỗi ở `detail`; endpoint cũ đặt ở `message`.
  static String? _error(http.Response res) {
    if (res.statusCode == 200) {
      try {
        final body = json.decode(utf8.decode(res.bodyBytes));
        if (body['status'] == 'success') return null;
        return '${body['message'] ?? 'Không thực hiện được.'}';
      } catch (_) {
        return 'Phản hồi không đọc được từ máy chủ.';
      }
    }
    if (res.statusCode == 401) {
      AuthService.handleUnauthorized();
      return 'Phiên đăng nhập đã hết hạn.';
    }
    try {
      final body = json.decode(utf8.decode(res.bodyBytes));
      return '${body['detail'] ?? body['message'] ?? 'Lỗi máy chủ (HTTP ${res.statusCode})'}';
    } catch (_) {
      return 'Lỗi máy chủ (HTTP ${res.statusCode})';
    }
  }

  // -------------------------------------------------------
  // Khu vực
  // -------------------------------------------------------
  static Future<List<Zone>?> fetchZones() async {
    try {
      final res = await http
          .get(Uri.parse('$_base/api/zones'), headers: await _headers())
          .timeout(AppConfig.apiTimeout);
      final data = _data(res);
      if (data == null) return null;
      return (data as List)
          .map((e) => Zone.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    } catch (_) {
      return null;
    }
  }

  static Future<String?> createZone(String name, {int sortOrder = 0}) async {
    try {
      final res = await http
          .post(
            Uri.parse('$_base/api/zones'),
            headers: await _headers(jsonBody: true),
            body: json.encode({'name': name, 'sort_order': sortOrder}),
          )
          .timeout(AppConfig.apiTimeout);
      return _error(res);
    } catch (_) {
      return 'Mất kết nối máy chủ.';
    }
  }

  static Future<String?> updateZone(int id, Map<String, dynamic> fields) async {
    try {
      final res = await http
          .patch(
            Uri.parse('$_base/api/zones/$id'),
            headers: await _headers(jsonBody: true),
            body: json.encode(fields),
          )
          .timeout(AppConfig.apiTimeout);
      return _error(res);
    } catch (_) {
      return 'Mất kết nối máy chủ.';
    }
  }

  static Future<String?> deleteZone(int id) async {
    try {
      final res = await http
          .delete(Uri.parse('$_base/api/zones/$id'), headers: await _headers())
          .timeout(AppConfig.apiTimeout);
      return _error(res);
    } catch (_) {
      return 'Mất kết nối máy chủ.';
    }
  }

  // -------------------------------------------------------
  // Thành viên
  // -------------------------------------------------------
  static Future<List<Member>?> fetchMembers() async {
    try {
      final res = await http
          .get(Uri.parse('$_base/api/members'), headers: await _headers())
          .timeout(AppConfig.apiTimeout);
      final data = _data(res);
      if (data == null) return null;
      return (data as List)
          .map((e) => Member.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    } catch (_) {
      return null;
    }
  }

  /// Duyệt / đổi vai / cấp khu. `zoneIds` thay CẢ BỘ grant (không phải thêm-bớt).
  static Future<String?> updateMember(
    String userId, {
    String? role,
    String? status,
    String? displayName,
    List<int>? zoneIds,
  }) async {
    try {
      final res = await http
          .patch(
            Uri.parse('$_base/api/members/$userId'),
            headers: await _headers(jsonBody: true),
            body: json.encode({
              if (role != null) 'role': role,
              if (status != null) 'status': status,
              if (displayName != null) 'display_name': displayName,
              if (zoneIds != null) 'zone_ids': zoneIds,
            }),
          )
          .timeout(AppConfig.apiTimeout);
      return _error(res);
    } catch (_) {
      return 'Mất kết nối máy chủ.';
    }
  }

  // -------------------------------------------------------
  // Gán thiết bị vào khu
  // -------------------------------------------------------
  /// [zoneId] null + [clearZone] true = đưa thiết bị về "Chưa phân khu".
  /// Cần cờ riêng vì null còn có nghĩa "không đổi trường này".
  static Future<String?> updateDevice(
    String deviceId, {
    String? name,
    int? zoneId,
    bool clearZone = false,
  }) async {
    try {
      final res = await http
          .patch(
            Uri.parse('$_base/api/devices/$deviceId'),
            headers: await _headers(jsonBody: true),
            body: json.encode({
              if (name != null) 'name': name,
              if (clearZone) 'zone_id': null else if (zoneId != null) 'zone_id': zoneId,
            }),
          )
          .timeout(AppConfig.apiTimeout);
      return _error(res);
    } catch (_) {
      return 'Mất kết nối máy chủ.';
    }
  }
}
