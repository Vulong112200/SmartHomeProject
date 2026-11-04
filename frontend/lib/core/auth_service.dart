import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'config.dart';

/// Ném ra khi không lấy được token — để caller phân biệt "chưa đăng nhập" với
/// "mất mạng". Trước đây header bị bỏ im lặng khi token null, server trả 401,
/// và UI báo "Mất kết nối máy chủ": sai chẩn đoán, sai cách phục hồi.
class NotAuthenticatedException implements Exception {
  final String message;
  const NotAuthenticatedException([this.message = 'Bạn chưa đăng nhập.']);
  @override
  String toString() => message;
}

/// Bọc Supabase Auth + gắn Bearer token vào request tới backend FastAPI.
///
/// Hai nguồn token, theo thứ tự ưu tiên:
///   1. Access token của Supabase (isolate chính, tự refresh).
///   2. **App-token** do backend cấp, lưu SharedPreferences.
///
/// Vì sao cần nguồn thứ hai: `widgetBackgroundCallback` và shortcut handler
/// chạy ở **isolate riêng**, nơi `Supabase.instance` chưa từng được khởi tạo.
/// Ở đó đọc session sẽ ném lỗi ⇒ Home Widget hiện "Không rõ" và nút bấm im
/// lặng không làm gì, không báo lỗi gì cả. Init Supabase trong isolate đó thì
/// hai isolate refresh song song, mà Supabase **xoay vòng refresh token** ⇒
/// isolate này vô hiệu hóa token của isolate kia, cả nhà bị đăng xuất ngẫu
/// nhiên. Cache access token 1 giờ thì hỏng mỗi khi bấm widget sau 1 giờ.
class AuthService {
  AuthService._();

  static const String _appTokenKey = 'app_token_v1';

  /// Đã gọi `init()` chưa. Isolate nền KHÔNG gọi init, nên cờ này false ở đó
  /// và mọi truy cập Supabase bị bỏ qua thay vì ném lỗi.
  static bool _supabaseReady = false;

  /// Callback khi phát hiện 401 — `AuthGate` gắn vào để đưa về màn đăng nhập.
  static void Function()? onUnauthorized;

  static SupabaseClient get _client => Supabase.instance.client;

  /// Khởi tạo Supabase. Gọi MỘT LẦN trong `main()`, trước `runApp`.
  /// Tuyệt đối không gọi trong isolate nền (xem doc của class).
  static Future<void> init() async {
    if (_supabaseReady) return;
    await Supabase.initialize(
      url: AppConfig.supabaseUrl,
      // ignore: deprecated_member_use
      anonKey: AppConfig.supabaseAnonKey,
    );
    _supabaseReady = true;
  }

  static bool get isConfigured => AppConfig.authEnabled;

  static Session? get session => _supabaseReady ? _client.auth.currentSession : null;
  static User? get user => _supabaseReady ? _client.auth.currentUser : null;
  static bool get isLoggedIn => session != null;
  static String get email => user?.email ?? '';

  /// Stream đổi trạng thái đăng nhập (cho AuthGate lắng nghe).
  static Stream<AuthState> get onAuthChange => _client.auth.onAuthStateChange;

  // -------------------------------------------------------
  // Token
  // -------------------------------------------------------
  /// Access token hiện tại, tự refresh nếu sắp hết hạn. Null nếu chưa đăng nhập.
  static Future<String?> accessToken() async {
    if (_supabaseReady) {
      var current = _client.auth.currentSession;
      if (current != null) {
        if (current.isExpired) {
          try {
            final refreshed = await _client.auth.refreshSession();
            current = refreshed.session;
          } catch (_) {
            current = null; // refresh hỏng -> rơi xuống app-token
          }
        }
        if (current != null) return current.accessToken;
      }
    }
    // Isolate nền, hoặc session hỏng: dùng token dài hạn do backend cấp.
    return await readAppToken();
  }

  /// Header kèm Bearer token. Ném [NotAuthenticatedException] nếu không có
  /// token — KHÔNG im lặng bỏ header rồi để server trả 401 khó hiểu.
  static Future<Map<String, String>> headers({bool jsonBody = false}) async {
    final token = await accessToken();
    if (token == null || token.isEmpty) {
      throw const NotAuthenticatedException();
    }
    return {
      'Authorization': 'Bearer $token',
      if (jsonBody) 'Content-Type': 'application/json',
    };
  }

  /// Gọi khi server trả 401: phiên đã chết, đưa người dùng về đăng nhập.
  /// ⚠️ 403 KHÁC 401 — 403 là "chờ chủ nhà duyệt", phải ra màn hình chờ chứ
  /// không phải đăng xuất.
  static Future<void> handleUnauthorized() async {
    await clearAppToken();
    try {
      if (_supabaseReady) await _client.auth.signOut();
    } catch (_) {}
    onUnauthorized?.call();
  }

  // -------------------------------------------------------
  // App-token (isolate nền)
  // -------------------------------------------------------
  static Future<String?> readAppToken() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString(_appTokenKey);
      return (token != null && token.isNotEmpty) ? token : null;
    } catch (_) {
      return null;
    }
  }

  static Future<void> clearAppToken() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_appTokenKey);
    } catch (_) {}
  }

  /// Xin backend cấp app-token rồi lưu lại. Gọi sau mỗi lần đăng nhập thành
  /// công. Không có nó thì Home Widget và shortcut hỏng âm thầm.
  static Future<bool> refreshAppToken() async {
    try {
      final token = await accessToken();
      if (token == null) return false;
      final res = await http
          .post(
            Uri.parse('${AppConfig.baseUrl}/api/auth/app-token'),
            headers: {'Authorization': 'Bearer $token'},
          )
          .timeout(AppConfig.apiTimeout);
      if (res.statusCode != 200) return false;
      final body = json.decode(utf8.decode(res.bodyBytes));
      final appToken = body['data']?['app_token'] as String?;
      if (appToken == null || appToken.isEmpty) return false;
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_appTokenKey, appToken);
      return true;
    } catch (_) {
      return false;
    }
  }

  // -------------------------------------------------------
  // Đăng nhập / đăng ký
  // -------------------------------------------------------
  static Future<void> signIn(String email, String password) async {
    await _client.auth.signInWithPassword(email: email.trim(), password: password);
    await refreshAppToken();
  }

  static Future<void> signUp(String email, String password, {String? displayName}) async {
    await _client.auth.signUp(
      email: email.trim(),
      password: password,
      data: displayName != null ? {'display_name': displayName} : null,
    );
    await refreshAppToken();
  }

  static Future<void> signOut() async {
    await clearAppToken();
    await _client.auth.signOut();
  }
}

/// Hồ sơ người dùng trong nhà, parse từ `GET /api/me`.
class HouseholdProfile {
  final String userId;
  final String email;
  final String displayName;
  /// Màu avatar "#RRGGBB" tự chọn ở màn Hồ sơ; null = màu tự suy từ userId.
  final String? avatarColor;
  final String role;    // owner | adult | kid | guest
  final String status;  // pending | active | blocked
  final bool canAdmin;
  final bool canSchedule;
  final List<int> zoneIds;
  final List<Map<String, dynamic>> zones;

  const HouseholdProfile({
    required this.userId,
    required this.email,
    required this.displayName,
    this.avatarColor,
    required this.role,
    required this.status,
    required this.canAdmin,
    required this.canSchedule,
    required this.zoneIds,
    required this.zones,
  });

  /// Bản sao với tên/màu mới (sau khi sửa ở màn Hồ sơ). [clearAvatarColor] = về màu tự động.
  HouseholdProfile copyWith({String? displayName, String? avatarColor, bool clearAvatarColor = false}) =>
      HouseholdProfile(
        userId: userId,
        email: email,
        displayName: displayName ?? this.displayName,
        avatarColor: clearAvatarColor ? null : (avatarColor ?? this.avatarColor),
        role: role,
        status: status,
        canAdmin: canAdmin,
        canSchedule: canSchedule,
        zoneIds: zoneIds,
        zones: zones,
      );

  /// Tên để chào/hiển thị: tên hiển thị > phần trước @ của email > null.
  String? get friendlyName {
    if (displayName.trim().isNotEmpty) return displayName.trim();
    if (email.contains('@')) return email.split('@').first;
    return null;
  }

  bool get isPending => status == 'pending';
  bool get isBlocked => status == 'blocked';
  bool get isActive => status == 'active';

  /// Mô tả ngắn phạm vi đang được dùng, cho menu tài khoản.
  String get scopeLabel {
    if (role == 'owner' || role == 'adult') return 'Thấy mọi khu vực';
    if (zones.isEmpty) return 'Chưa được cấp khu vực nào';
    return 'Khu: ${zones.map((z) => z['name']).join(', ')}';
  }

  factory HouseholdProfile.fromJson(Map<String, dynamic> j) => HouseholdProfile(
        userId: '${j['user_id'] ?? ''}',
        email: '${j['email'] ?? ''}',
        displayName: '${j['display_name'] ?? ''}',
        avatarColor: j['avatar_color'] as String?,
        role: '${j['role'] ?? 'guest'}',
        status: '${j['status'] ?? 'pending'}',
        canAdmin: j['can_admin'] == true,
        canSchedule: j['can_schedule'] == true,
        // num -> int: JSON số nguyên có thể về dạng double ở vài nền tảng.
        zoneIds: ((j['zone_ids'] as List?) ?? []).whereType<num>().map((e) => e.toInt()).toList(),
        zones: ((j['zones'] as List?) ?? [])
            .map((e) => Map<String, dynamic>.from(e as Map))
            .toList(),
      );

  /// Hồ sơ giả khi backend đang chạy với xác thực TẮT (chưa cấu hình Supabase).
  /// Giữ app dùng được y như trước trong lúc chuyển tiếp.
  static const HouseholdProfile openHouse = HouseholdProfile(
    userId: '',
    email: '',
    displayName: '',
    role: 'owner',
    status: 'active',
    canAdmin: true,
    canSchedule: true,
    zoneIds: [],
    zones: [],
  );
}

/// Kết quả gọi `/api/me` — phân biệt rõ 4 tình huống thay vì trả null chung.
enum MeResult { ok, unauthorized, offline, serverError }

class MeResponse {
  final MeResult result;
  final HouseholdProfile? profile;
  const MeResponse(this.result, [this.profile]);
}

/// Gọi `GET /api/me`. Tách khỏi AuthService vì nó nói chuyện với backend của
/// mình, không phải với Supabase.
Future<MeResponse> fetchMe() async {
  try {
    final token = await AuthService.accessToken();
    final res = await http.get(
      Uri.parse('${AppConfig.baseUrl}/api/me'),
      headers: {if (token != null) 'Authorization': 'Bearer $token'},
    ).timeout(AppConfig.apiTimeout);

    if (res.statusCode == 401) return const MeResponse(MeResult.unauthorized);
    if (res.statusCode != 200) return const MeResponse(MeResult.serverError);

    final body = json.decode(utf8.decode(res.bodyBytes));
    if (body['status'] != 'success') return const MeResponse(MeResult.serverError);
    return MeResponse(
      MeResult.ok,
      HouseholdProfile.fromJson(Map<String, dynamic>.from(body['data'] ?? {})),
    );
  } catch (_) {
    return const MeResponse(MeResult.offline);
  }
}
