import 'package:flutter/material.dart';

import 'device_api.dart';
import 'shortcut_service.dart';

/// NavigatorKey toàn cục để hiện dialog/snackbar từ shortcut khi không có
/// BuildContext trực tiếp (vd app vừa mở do bấm icon).
final GlobalKey<NavigatorState> appNavigatorKey = GlobalKey<NavigatorState>();

/// Điều phối hành vi khi người dùng bấm icon shortcut.
class ShortcutHandler {
  /// Đăng ký với ShortcutService trong main().
  static Future<void> register() async {
    await ShortcutService.instance.initialize(handle);
  }

  static Future<void> handle(ShortcutAction action) async {
    switch (action.type) {
      case ShortcutType.purifierCycle:
        await _handlePurifierCycle(action);
        break;
      case ShortcutType.feederFeed:
        await _confirm(
          action,
          title: 'Cho ăn 1 lần?',
          message: 'Nhả 1 phần thức ăn cho ${action.deviceName}.',
          onYes: () => DeviceApi.sendMode(action.brand, action.deviceId, '1'),
          successMsg: 'Đã cho ăn 1 lần 🐾',
        );
        break;
      case ShortcutType.doorOpen:
        await _confirm(
          action,
          title: 'Mở cửa?',
          message: 'Xác nhận MỞ ${action.deviceName}.',
          onYes: () => DeviceApi.sendMode(action.brand, action.deviceId, 'open'),
          successMsg: 'Đang mở cửa...',
        );
        break;
      case ShortcutType.doorClose:
        await _confirm(
          action,
          title: 'Đóng cửa?',
          message: 'Xác nhận ĐÓNG ${action.deviceName}.',
          onYes: () => DeviceApi.sendMode(action.brand, action.deviceId, 'close'),
          successMsg: 'Đang đóng cửa...',
        );
        break;
      case ShortcutType.doorToggle:
        await _handleDoorToggle(action);
        break;
    }
  }

  /// Cửa (1 icon thông minh): đọc trạng thái thật → hỏi mở/đóng chiều ngược lại
  /// (chống nhấn nhầm khi ở ngoài). Backend tự chèn 'stop' trước open/close.
  static Future<void> _handleDoorToggle(ShortcutAction action) async {
    final status = await DeviceApi.fetchStatus(action.brand, action.deviceId);
    final doorState = '${status?['door_state']}'.toLowerCase();
    final isClosed = doorState == 'closed' || doorState == 'closing';
    final willOpen = isClosed; // đang đóng → mở; ngược lại → đóng
    final targetMode = willOpen ? 'open' : 'close';

    await _confirm(
      action,
      title: willOpen ? 'Mở cửa?' : 'Đóng cửa?',
      message: 'Xác nhận ${willOpen ? "MỞ" : "ĐÓNG"} ${action.deviceName}.',
      onYes: () async {
        final ok = await DeviceApi.sendMode(action.brand, action.deviceId, targetMode);
        if (ok) {
          await ShortcutService.instance.updateShortcutIcon(
            action,
            label: action.deviceName,
            iconRes: ShortcutIcons.door(willOpen ? 'open' : 'closed'),
          );
        }
        return ok;
      },
      successMsg: willOpen ? 'Đang mở cửa...' : 'Đang đóng cửa...',
    );
  }

  /// Máy lọc: đọc trạng thái thật → tính bước kế tiếp → thực thi → cập nhật icon.
  static Future<void> _handlePurifierCycle(ShortcutAction action) async {
    final status = await DeviceApi.fetchStatus(action.brand, action.deviceId);
    final currentIndex = PurifierCycle.indexFromStatus(status);
    final step = PurifierCycle.next(currentIndex);

    final ok = await PurifierCycle.apply(action.brand, action.deviceId, step);

    if (ok) {
      // Cập nhật icon shortcut cho khớp trạng thái mới (chống hiển thị sai).
      await ShortcutService.instance.updateShortcutIcon(
        action,
        label: '${action.deviceName} • ${step.label}',
        iconRes: ShortcutIcons.purifier(step.key),
      );
    }
    _snack(ok ? '${action.deviceName}: ${step.label}' : 'Lỗi kết nối thiết bị', ok);
  }

  static Future<void> _confirm(
    ShortcutAction action, {
    required String title,
    required String message,
    required Future<bool> Function() onYes,
    required String successMsg,
  }) async {
    final ctx = await _waitForContext();
    if (ctx == null || !ctx.mounted) return;

    final confirmed = await showDialog<bool>(
      // ctx là context của Navigator toàn cục (persistent), an toàn dùng ở đây.
      // ignore: use_build_context_synchronously
      context: ctx,
      builder: (c) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Huỷ')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Xác nhận')),
        ],
      ),
    );

    if (confirmed == true) {
      final ok = await onYes();
      _snack(ok ? successMsg : 'Lỗi kết nối thiết bị', ok);
    }
  }

  static void _snack(String msg, bool ok) {
    final ctx = appNavigatorKey.currentContext;
    if (ctx == null) return;
    ScaffoldMessenger.of(ctx).showSnackBar(
      SnackBar(
        content: Text(msg),
        backgroundColor: ok ? Colors.green : Colors.redAccent,
        duration: const Duration(seconds: 2),
      ),
    );
  }

  /// Chờ Navigator sẵn sàng (app vừa khởi động từ shortcut có thể chưa dựng xong).
  static Future<BuildContext?> _waitForContext() async {
    for (int i = 0; i < 20; i++) {
      final ctx = appNavigatorKey.currentContext;
      if (ctx != null) return ctx;
      await Future.delayed(const Duration(milliseconds: 150));
    }
    return appNavigatorKey.currentContext;
  }
}

/// Ánh xạ trạng thái → tên drawable Android cho icon shortcut.
/// Nếu drawable chưa tồn tại, native tự fallback về launcher_icon (an toàn).
class ShortcutIcons {
  static String purifier(String stepKey) {
    switch (stepKey) {
      case 'off':
        return 'ic_purifier_off';
      case 'on':
        return 'ic_purifier_on';
      case 'low':
        return 'ic_purifier_low';
      case 'med':
        return 'ic_purifier_med';
      case 'high':
        return 'ic_purifier_high';
      case 'auto':
        return 'ic_purifier_auto';
      case 'sleep':
        return 'ic_purifier_sleep';
      default:
        return 'launcher_icon';
    }
  }

  static String feeder() => 'ic_feeder';

  static String door(String doorState) {
    switch (doorState) {
      case 'open':
      case 'opening':
      case 'partial':
        return 'ic_door_open';
      case 'closed':
      case 'closing':
        return 'ic_door_closed';
      default:
        return 'launcher_icon';
    }
  }
}
