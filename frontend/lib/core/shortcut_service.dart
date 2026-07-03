import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:quick_actions/quick_actions.dart';

/// Kiểu shortcut theo loại thiết bị.
class ShortcutType {
  static const String purifierCycle = 'purifier_cycle';
  static const String feederFeed = 'feeder_feed';
  static const String doorOpen = 'door_open';
  static const String doorClose = 'door_close';
  // 1 icon cửa thông minh: đọc trạng thái rồi hỏi mở/đóng chiều ngược lại.
  static const String doorToggle = 'door_toggle';
}

/// Payload đi kèm mỗi shortcut/quick-action.
class ShortcutAction {
  final String type;
  final String brand;
  final String deviceId;
  final String deviceName;

  const ShortcutAction({
    required this.type,
    required this.brand,
    required this.deviceId,
    required this.deviceName,
  });

  /// ID ổn định cho 1 shortcut (mỗi thiết bị/loại action là duy nhất).
  String get id => '${type}_$deviceId';

  Map<String, String> toMap() => {
        'type': type,
        'brand': brand,
        'deviceId': deviceId,
        'deviceName': deviceName,
      };

  /// Mã hoá thành 1 chuỗi cho quick_actions (iOS) vì nó chỉ nhận 1 string type.
  String encode() => '$type|$brand|$deviceId|$deviceName';

  static ShortcutAction? tryDecode(String raw) {
    final parts = raw.split('|');
    if (parts.length < 3) return null;
    return ShortcutAction(
      type: parts[0],
      brand: parts[1],
      deviceId: parts[2],
      deviceName: parts.length > 3 ? parts[3] : parts[2],
    );
  }

  static ShortcutAction? fromMap(Map<dynamic, dynamic>? m) {
    if (m == null) return null;
    final type = m['type']?.toString();
    final brand = m['brand']?.toString();
    final deviceId = m['deviceId']?.toString();
    if (type == null || brand == null || deviceId == null) return null;
    return ShortcutAction(
      type: type,
      brand: brand,
      deviceId: deviceId,
      deviceName: m['deviceName']?.toString() ?? deviceId,
    );
  }
}

typedef ShortcutActionHandler = void Function(ShortcutAction action);

/// Dịch vụ tạo icon shortcut trên home screen.
///
/// - Android: gọi native (MethodChannel) `ShortcutManagerCompat.requestPinShortcut`
///   để sinh icon RỜI ngoài màn hình chính + cập nhật icon theo trạng thái.
/// - iOS: dùng `quick_actions` (Home Screen Quick Actions khi nhấn-giữ icon app).
///   iOS không cho tạo icon rời bằng code — người dùng có thể thêm thủ công qua
///   app Shortcuts bằng URL scheme.
class ShortcutService {
  ShortcutService._();
  static final ShortcutService instance = ShortcutService._();

  static const MethodChannel _channel = MethodChannel('smarthome/shortcuts');
  final QuickActions _quickActions = const QuickActions();

  // iOS: setShortcutItems thay thế toàn bộ danh sách, nên tích luỹ để không
  // ghi đè các quick action đã tạo trong phiên.
  final Map<String, ShortcutItem> _iosItems = {};

  ShortcutActionHandler? _handler;

  /// Khởi tạo listener. Gọi 1 lần trong main().
  Future<void> initialize(ShortcutActionHandler handler) async {
    _handler = handler;

    // Nhận action từ native (Android) khi app đang chạy hoặc vừa mở.
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'onShortcutAction') {
        final action = ShortcutAction.fromMap(call.arguments as Map?);
        if (action != null) _dispatch(action);
      }
    });

    // iOS/Android long-press quick actions.
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      _quickActions.initialize((raw) {
        final action = ShortcutAction.tryDecode(raw);
        if (action != null) _dispatch(action);
      });
    }

    // Trường hợp app được MỞ từ trạng thái tắt do bấm shortcut (Android).
    await _consumeInitialAction();
  }

  void _dispatch(ShortcutAction action) {
    _handler?.call(action);
  }

  Future<void> _consumeInitialAction() async {
    if (defaultTargetPlatform != TargetPlatform.android) return;
    try {
      final res = await _channel.invokeMethod('getInitialAction');
      final action = ShortcutAction.fromMap(res as Map?);
      if (action != null) _dispatch(action);
    } on PlatformException {
      // ignore
    } on MissingPluginException {
      // ignore (chạy trên nền tảng chưa có native)
    }
  }

  Future<bool> isPinSupported() async {
    if (defaultTargetPlatform != TargetPlatform.android) return false;
    try {
      final res = await _channel.invokeMethod('isPinSupported');
      return res == true;
    } catch (_) {
      return false;
    }
  }

  /// Tạo icon shortcut rời trên home screen cho 1 thiết bị.
  /// [iconRes]: tên drawable/mipmap Android tương ứng trạng thái (mặc định
  /// dùng launcher_icon). Trả về true nếu đã gửi yêu cầu pin.
  Future<bool> pinShortcut(
    ShortcutAction action, {
    required String label,
    String iconRes = 'launcher_icon',
  }) async {
    if (defaultTargetPlatform == TargetPlatform.android) {
      try {
        final ok = await _channel.invokeMethod('pinShortcut', {
          'id': action.id,
          'shortLabel': label,
          'longLabel': label,
          'iconRes': iconRes,
          ...action.toMap(),
        });
        return ok == true;
      } catch (_) {
        return false;
      }
    } else {
      // iOS: đăng ký quick action (long-press icon app), tích luỹ danh sách.
      _iosItems[action.id] = ShortcutItem(
        type: action.encode(),
        localizedTitle: label,
        icon: 'launcher_icon',
      );
      await _quickActions.setShortcutItems(_iosItems.values.toList());
      return true;
    }
  }

  /// Cập nhật icon của shortcut đã tạo cho khớp trạng thái thật (chỉ Android).
  Future<void> updateShortcutIcon(
    ShortcutAction action, {
    required String label,
    required String iconRes,
  }) async {
    if (defaultTargetPlatform != TargetPlatform.android) return;
    try {
      await _channel.invokeMethod('updateShortcut', {
        'id': action.id,
        'shortLabel': label,
        'iconRes': iconRes,
        ...action.toMap(),
      });
    } catch (_) {
      // ignore
    }
  }
}
