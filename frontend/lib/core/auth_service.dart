import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

import 'config.dart';

/// Bọc Supabase Auth + helper gắn Bearer token vào request tới backend FastAPI.
///
/// Supabase tự lưu session (SharedPreferences) & tự refresh token nền, nên chỉ
/// cần đọc `currentSession.accessToken` mỗi lần gọi API.
class AuthService {
  static SupabaseClient get _client => Supabase.instance.client;

  /// Khởi tạo Supabase (gọi 1 lần trong main, trước runApp).
  static Future<void> init() async {
    await Supabase.initialize(
      url: AppConfig.supabaseUrl,
      // Dùng "anon public" key theo hướng dẫn Supabase. (publishableKey là tên
      // mới ở SDK 2.8 nhưng nhận cùng giá trị; giữ anonKey cho khớp dashboard.)
      // ignore: deprecated_member_use
      anonKey: AppConfig.supabaseAnonKey,
    );
  }

  static Session? get session => _client.auth.currentSession;
  static User? get user => _client.auth.currentUser;
  static bool get isLoggedIn => session != null;
  static String get email => user?.email ?? '';

  /// Stream đổi trạng thái đăng nhập (cho AuthGate lắng nghe).
  static Stream<AuthState> get onAuthChange => _client.auth.onAuthStateChange;

  /// Header kèm Bearer token. jsonBody=true để thêm Content-Type khi POST/PATCH.
  static Map<String, String> authHeaders({bool jsonBody = false}) {
    final token = session?.accessToken;
    return {
      if (token != null) 'Authorization': 'Bearer $token',
      if (jsonBody) 'Content-Type': 'application/json',
    };
  }

  static Future<void> signIn(String email, String password) async {
    await _client.auth.signInWithPassword(email: email.trim(), password: password);
  }

  static Future<void> signUp(String email, String password, {String? displayName}) async {
    await _client.auth.signUp(
      email: email.trim(),
      password: password,
      data: displayName != null ? {'display_name': displayName} : null,
    );
  }

  static Future<void> signOut() async {
    await _client.auth.signOut();
  }

  /// Hỏi backend user hiện tại có phải admin không (dựa ADMIN_EMAILS server).
  /// Trả về {user_id, email, is_admin} hoặc null nếu lỗi.
  static Future<Map<String, dynamic>?> fetchMe() async {
    try {
      final res = await http
          .get(Uri.parse('${AppConfig.baseUrl}/api/me'), headers: authHeaders())
          .timeout(AppConfig.apiTimeout);
      if (res.statusCode == 200) {
        final body = json.decode(utf8.decode(res.bodyBytes));
        if (body['status'] == 'success') {
          return Map<String, dynamic>.from(body['data'] ?? {});
        }
      }
    } catch (_) {}
    return null;
  }
}
