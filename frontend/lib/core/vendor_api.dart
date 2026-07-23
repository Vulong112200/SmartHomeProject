import 'dart:convert';
import 'package:http/http.dart' as http;

import 'config.dart';
import 'auth_service.dart';

/// (data, error): error == null nghĩa là thành công.
typedef ListResult = (List<Map<String, dynamic>>? data, String? error);
typedef MapResult = (Map<String, dynamic>? data, String? error);

/// Gọi các endpoint kết nối nhà cung cấp / khám phá thiết bị / admin.
class VendorApi {
  static const String _base = AppConfig.baseUrl;
  static const Duration _t = Duration(seconds: 30); // login cloud có thể chậm

  static List<Map<String, dynamic>> _asList(dynamic data) =>
      ((data as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)).toList();

  // ---------- VeSync ----------
  static Future<ListResult> vesyncConnect(String email, String password) async {
    try {
      final res = await http
          .post(Uri.parse('$_base/api/vendor/vesync/connect'),
              headers: AuthService.authHeaders(jsonBody: true),
              body: json.encode({'email': email, 'password': password}))
          .timeout(_t);
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body['status'] == 'success') {
        return (_asList(body['data']), null);
      }
      return (null, '${body['message'] ?? 'Lỗi kết nối VeSync'}');
    } catch (_) {
      return (null, 'Mất kết nối máy chủ.');
    }
  }

  // ---------- Import ----------
  static Future<String?> importDevices(List<Map<String, dynamic>> devices) async {
    try {
      final res = await http
          .post(Uri.parse('$_base/api/devices/import'),
              headers: AuthService.authHeaders(jsonBody: true),
              body: json.encode({'devices': devices}))
          .timeout(AppConfig.apiTimeout);
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body['status'] == 'success') return null;
      return '${body['message'] ?? 'Lỗi thêm thiết bị'}';
    } catch (_) {
      return 'Mất kết nối máy chủ.';
    }
  }

  // ---------- Tuya ----------
  static Future<MapResult> tuyaLinkInfo() async {
    try {
      final res = await http
          .get(Uri.parse('$_base/api/vendor/tuya/link-info'),
              headers: AuthService.authHeaders())
          .timeout(AppConfig.apiTimeout);
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body['status'] == 'success') {
        return (Map<String, dynamic>.from(body['data'] ?? {}), null);
      }
      return (null, '${body['message'] ?? 'Lỗi'}');
    } catch (_) {
      return (null, 'Mất kết nối máy chủ.');
    }
  }

  static Future<ListResult> tuyaDiscover() async {
    try {
      final res = await http
          .post(Uri.parse('$_base/api/vendor/tuya/discover'),
              headers: AuthService.authHeaders())
          .timeout(_t);
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body['status'] == 'success') {
        return (_asList(body['data']), null);
      }
      return (null, '${body['message'] ?? 'Lỗi lấy thiết bị Tuya'}');
    } catch (_) {
      return (null, 'Mất kết nối máy chủ.');
    }
  }

  // ---------- Admin ----------
  static Future<ListResult> adminUsers() async {
    return _getList('$_base/api/admin/users');
  }

  static Future<ListResult> adminUserDevices(String uid) async {
    return _getList('$_base/api/admin/users/$uid/devices');
  }

  static Future<ListResult> adminTuyaLinked() async {
    return _getList('$_base/api/admin/tuya/linked');
  }

  static Future<String?> adminAssignTuya(String userId, String tuyaUid) async {
    try {
      final res = await http
          .post(Uri.parse('$_base/api/admin/vendor/tuya/assign'),
              headers: AuthService.authHeaders(jsonBody: true),
              body: json.encode({'user_id': userId, 'tuya_uid': tuyaUid}))
          .timeout(AppConfig.apiTimeout);
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body['status'] == 'success') return null;
      return '${body['message'] ?? 'Lỗi gán tài khoản'}';
    } catch (_) {
      return 'Mất kết nối máy chủ.';
    }
  }

  static Future<String?> adminImportDevices(
      String userId, List<Map<String, dynamic>> devices) async {
    try {
      final res = await http
          .post(Uri.parse('$_base/api/admin/devices/import'),
              headers: AuthService.authHeaders(jsonBody: true),
              body: json.encode({'user_id': userId, 'devices': devices}))
          .timeout(AppConfig.apiTimeout);
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body['status'] == 'success') return null;
      return '${body['message'] ?? 'Lỗi thêm thiết bị'}';
    } catch (_) {
      return 'Mất kết nối máy chủ.';
    }
  }

  static Future<ListResult> _getList(String url) async {
    try {
      final res = await http
          .get(Uri.parse(url), headers: AuthService.authHeaders())
          .timeout(_t);
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (res.statusCode == 200 && body['status'] == 'success') {
        return (_asList(body['data']), null);
      }
      if (res.statusCode == 403) return (null, 'Bạn không có quyền admin.');
      return (null, '${body['message'] ?? 'Lỗi máy chủ'}');
    } catch (_) {
      return (null, 'Mất kết nối máy chủ.');
    }
  }
}
