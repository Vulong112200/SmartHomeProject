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
}
