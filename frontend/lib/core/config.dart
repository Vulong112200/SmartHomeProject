/// Cấu hình chung của app — nơi DUY NHẤT khai báo địa chỉ backend.
/// (Trước đây baseUrl bị lặp ở device_api / dashboard / ai_assistant,
/// còn WebSocket trỏ nhầm IP LAN chết.)
class AppConfig {
  AppConfig._();

  /// Backend FastAPI (deploy Render, được UptimeRobot giữ thức).
  static const String baseUrl = 'https://vuhp-smarthome.onrender.com';

  /// WebSocket cùng host với backend (wss vì Render chạy HTTPS).
  static const String wsUrl = 'wss://vuhp-smarthome.onrender.com/ws';

  /// Timeout chuẩn cho các request API thường (status/control/devices).
  static const Duration apiTimeout = Duration(seconds: 6);

  /// Timeout dài cho lần ping /health đầu (Render cold start 30-50s).
  static const Duration healthTimeout = Duration(seconds: 35);

  /// Supabase Auth. Lấy ở Dashboard > Project Settings > API.
  /// Build kèm khóa thật:
  ///   flutter build apk --dart-define=SUPABASE_URL=... --dart-define=SUPABASE_ANON_KEY=...
  ///
  /// Để mặc định (chưa điền) thì app BỎ QUA đăng nhập và chạy y như trước —
  /// khớp với backend đang để xác thực TẮT. Nhờ vậy cài bản build chưa cấu
  /// hình lên máy vẫn dùng được, không ai bị khóa ngoài nhà mình.
  ///
  /// anon key nằm trong APK nên KHÔNG phải bí mật; an toàn đến từ việc mọi
  /// bảng đều bật RLS deny-all (xem backend/docs/supabase_schema.sql).
  static const String supabaseUrl = String.fromEnvironment(
    'SUPABASE_URL',
    defaultValue: '',
  );
  static const String supabaseAnonKey = String.fromEnvironment(
    'SUPABASE_ANON_KEY',
    defaultValue: '',
  );

  /// Có bật luồng đăng nhập không. Thiếu khóa thì không thể đăng nhập, nên
  /// bật lên chỉ làm app kẹt ở màn login vĩnh viễn.
  static bool get authEnabled =>
      supabaseUrl.isNotEmpty && supabaseAnonKey.isNotEmpty;
}
