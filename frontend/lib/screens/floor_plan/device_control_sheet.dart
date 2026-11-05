import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../core/device_status.dart';
import '../../core/device_type.dart';
import '../../theme/app_colors.dart';
import 'plan_device.dart';

/// Bảng điều khiển 1 thiết bị, mở khi chạm icon trên sơ đồ.
///
/// Hành động lấy từ `deviceActionOptions` — CÙNG danh sách với form Hẹn giờ /
/// Kịch bản, khớp whitelist backend (cửa chỉ mở/dừng/đóng, máy cho ăn 1-3 phần
/// như Dashboard). Gửi lệnh do màn Sơ đồ làm qua DeviceApi có sẵn; bảng này
/// chỉ hiển thị trạng thái sống (`live`) + kết quả lệnh.
Future<void> showDeviceControlSheet(
  BuildContext context, {
  required PlanDevice device,
  required ValueListenable<DeviceLive> live,
  required ValueListenable<bool> serverOffline,
  required Future<void> Function(DeviceActionOption option) onAction,
}) {
  return showModalBottomSheet<void>(
    context: context,
    backgroundColor: context.palette.surface,
    showDragHandle: true,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    builder: (_) => DeviceControlPanel(device: device, live: live, serverOffline: serverOffline, onAction: onAction),
  );
}

/// Thứ tự nút cửa: Mở – Dừng – Đóng (giống Dashboard), các loại khác giữ nguyên.
List<DeviceActionOption> _orderedOptions(DeviceType type) {
  final opts = deviceActionOptions(type);
  if (type != DeviceType.curtain) return opts;
  const order = ['mode:open', 'mode:stop', 'mode:close'];
  return [...opts]..sort((a, b) => order.indexOf(a.key).compareTo(order.indexOf(b.key)));
}

class DeviceControlPanel extends StatelessWidget {
  final PlanDevice device;
  final ValueListenable<DeviceLive> live;
  final ValueListenable<bool> serverOffline;
  final Future<void> Function(DeviceActionOption option) onAction;

  const DeviceControlPanel({
    super.key,
    required this.device,
    required this.live,
    required this.serverOffline,
    required this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final accent = deviceAccentOf(context, device.type);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
        child: AnimatedBuilder(
          animation: Listenable.merge([live, serverOffline]),
          builder: (context, _) {
            final l = live.value;
            final offline = serverOffline.value;
            final view = l.view(device.type);
            final activeKey = l.pendingKey ?? currentActionKey(device.type, l.status);
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(color: accent.withValues(alpha: 0.18), shape: BoxShape.circle),
                      child: Icon(deviceIconOf(device.type, l.status), color: accent),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(device.name,
                              style: TextStyle(color: p.textMain, fontSize: 17, fontWeight: FontWeight.bold)),
                          Text(
                            [if (device.zoneName != null) device.zoneName!, view.label].join(' • '),
                            style: TextStyle(
                              color: view.state == DeviceVisualState.offline ? offlineColor : p.textSub,
                              fontSize: 13,
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (l.sending)
                      SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: p.primary)),
                  ],
                ),
                const SizedBox(height: 16),
                if (offline)
                  const _Note(Icons.wifi_off, 'Mất kết nối máy chủ — chưa điều khiển được. Đang thử kết nối lại...',
                      offlineColor),
                if (!offline && view.state == DeviceVisualState.offline)
                  const _Note(Icons.cloud_off, 'Thiết bị đang mất kết nối với cloud của hãng — lệnh có thể không tới.',
                      offlineColor),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final opt in _orderedOptions(device.type))
                      ChoiceChip(
                        key: ValueKey('plan-action-${opt.key}'),
                        label: Text(opt.label),
                        selected: opt.key == activeKey,
                        showCheckmark: false,
                        selectedColor: opt.key == 'mode:stop' ? Colors.redAccent : accent,
                        labelStyle: TextStyle(
                          color: opt.key == activeKey ? Colors.white : p.textMain,
                          fontWeight: FontWeight.w600,
                          fontSize: 13,
                        ),
                        onSelected: (offline || l.sending) ? null : (_) => onAction(opt),
                      ),
                  ],
                ),
                if (device.type == DeviceType.feeder) ...[
                  const SizedBox(height: 8),
                  Text('Mỗi lần nhả tối đa 3 phần.', style: TextStyle(color: p.textSub, fontSize: 12)),
                ],
                if (l.message != null) ...[
                  const SizedBox(height: 14),
                  _Note(
                    switch (l.feedback) {
                      CommandFeedback.success => Icons.check_circle_outline,
                      CommandFeedback.error => Icons.error_outline,
                      CommandFeedback.warning => Icons.info_outline,
                      _ => Icons.hourglass_top,
                    },
                    l.message!,
                    switch (l.feedback) {
                      CommandFeedback.success => p.success,
                      CommandFeedback.error => offlineColor,
                      CommandFeedback.warning => Colors.orange,
                      _ => p.textSub,
                    },
                    key: const ValueKey('plan-command-message'),
                  ),
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _Note extends StatelessWidget {
  final IconData icon;
  final String text;
  final Color color;
  const _Note(this.icon, this.text, this.color, {super.key});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 18, color: color),
            const SizedBox(width: 8),
            Expanded(child: Text(text, style: TextStyle(color: color, fontSize: 13))),
          ],
        ),
      );
}
