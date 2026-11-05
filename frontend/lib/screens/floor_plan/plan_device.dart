import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../core/device_status.dart';
import '../../core/device_type.dart';
import '../../theme/app_colors.dart';

/// Thiết bị như sơ đồ cần (rút từ phần tử `/api/devices`).
class PlanDevice {
  final String id;
  final String name;
  final String brand;
  final DeviceType type;
  final String? zoneName;

  const PlanDevice({required this.id, required this.name, required this.brand, required this.type, this.zoneName});

  factory PlanDevice.fromApi(Map<String, dynamic> d) {
    final name = '${d['name'] ?? ''}';
    return PlanDevice(
      id: '${d['id']}',
      name: name,
      brand: '${d['brand'] ?? ''}'.toLowerCase(),
      type: deviceTypeOf(name, category: d['category'] as String?),
      zoneName: d['zone_name'] as String?,
    );
  }
}

enum CommandFeedback { none, info, success, warning, error }

/// Trạng thái sống của 1 thiết bị trên sơ đồ. Mỗi thiết bị có ValueNotifier
/// riêng ⇒ chỉ icon (và bảng điều khiển đang mở) của nó được vẽ lại.
@immutable
class DeviceLive {
  /// Trạng thái THẬT gần nhất backend trả về (null = chưa đọc được lần nào).
  final Map<String, dynamic>? status;

  /// Số lần đọc trạng thái lỗi liên tiếp (máy chủ không trả lời).
  final int readFailures;

  /// Đang gửi lệnh / chờ thiết bị xác nhận.
  final bool sending;

  /// `DeviceActionOption.key` của lệnh đang chờ xác nhận (tô sáng lạc quan).
  final String? pendingKey;

  /// Kết quả lệnh gần nhất, hiện trong bảng điều khiển.
  final String? message;
  final CommandFeedback feedback;

  const DeviceLive({
    this.status,
    this.readFailures = 0,
    this.sending = false,
    this.pendingKey,
    this.message,
    this.feedback = CommandFeedback.none,
  });

  static const _keep = Object();

  DeviceLive copyWith({
    Object? status = _keep,
    int? readFailures,
    bool? sending,
    Object? pendingKey = _keep,
    Object? message = _keep,
    CommandFeedback? feedback,
  }) =>
      DeviceLive(
        status: identical(status, _keep) ? this.status : status as Map<String, dynamic>?,
        readFailures: readFailures ?? this.readFailures,
        sending: sending ?? this.sending,
        pendingKey: identical(pendingKey, _keep) ? this.pendingKey : pendingKey as String?,
        message: identical(message, _keep) ? this.message : message as String?,
        feedback: feedback ?? this.feedback,
      );

  /// 2 lần đọc lỗi liên tiếp ⇒ trạng thái đang hiện có thể đã cũ.
  bool get stale => readFailures >= 2;

  DeviceStatusView view(DeviceType type) {
    if (stale) return const DeviceStatusView(DeviceVisualState.unknown, 'Không đọc được trạng thái');
    return describeDeviceStatus(type, status);
  }
}

/// Icon + màu nhận diện theo loại (khớp thẻ ở Dashboard).
IconData deviceIconOf(DeviceType type, [Map<String, dynamic>? status]) {
  switch (type) {
    case DeviceType.airPurifier:
      return Icons.air;
    case DeviceType.feeder:
      return Icons.pets;
    case DeviceType.curtain:
      final ds = '${status?['door_state'] ?? ''}'.toLowerCase();
      return (ds == 'closed' || ds == 'closing') ? Icons.blinds_closed : Icons.blinds;
    case DeviceType.powerSwitch:
      return Icons.water_drop;
    case DeviceType.unknown:
      return Icons.device_hub;
  }
}

Color deviceAccentOf(BuildContext context, DeviceType type) {
  final p = context.palette;
  switch (type) {
    case DeviceType.airPurifier:
      return p.cyan;
    case DeviceType.feeder:
      return p.purple;
    case DeviceType.curtain:
      return p.success;
    case DeviceType.powerSwitch:
      return p.cyan;
    case DeviceType.unknown:
      return p.primary;
  }
}

/// Màu báo mất kết nối (đủ tương phản ở cả nền sáng lẫn tối).
const Color offlineColor = Color(0xFFE5484D);

/// Icon thiết bị trên sơ đồ: vòng tròn (màu theo trạng thái) + tên + trạng thái.
///
/// Tâm vòng tròn nằm ĐÚNG ở tọa độ thiết bị: [iconDiameter]/2 tính từ đỉnh widget.
class DeviceMarker extends StatelessWidget {
  final PlanDevice device;
  final ValueListenable<DeviceLive> live;
  final VoidCallback? onTap;
  final bool editing;

  const DeviceMarker({super.key, required this.device, required this.live, this.onTap, this.editing = false});

  static const double iconDiameter = 44;
  static const double width = 104;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: width,
      child: ValueListenableBuilder<DeviceLive>(
        valueListenable: live,
        builder: (context, l, _) {
          final p = context.palette;
          final accent = deviceAccentOf(context, device.type);
          final view = l.view(device.type);
          final state = view.state;
          final lit = state == DeviceVisualState.active || state == DeviceVisualState.moving;
          final dim = state == DeviceVisualState.offline || state == DeviceVisualState.unknown;

          final circle = Container(
            width: iconDiameter,
            height: iconDiameter,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: lit ? accent : p.card,
              border: Border.all(
                color: state == DeviceVisualState.offline
                    ? offlineColor
                    : dim
                        ? p.textSub.withValues(alpha: 0.5)
                        : accent,
                width: 2,
              ),
              boxShadow: lit ? [BoxShadow(color: accent.withValues(alpha: 0.55), blurRadius: 14, spreadRadius: 1)] : null,
            ),
            child: Icon(
              deviceIconOf(device.type, l.status),
              size: 22,
              color: lit ? Colors.white : (dim ? p.textSub : accent),
            ),
          );

          return Semantics(
            button: onTap != null,
            label: '${device.name}, ${view.label}',
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: onTap,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(
                    key: ValueKey('plan-device-icon-${device.id}'),
                    width: iconDiameter,
                    height: iconDiameter,
                    child: Stack(
                      clipBehavior: Clip.none,
                      children: [
                        circle,
                        // Đang gửi / cửa đang chạy / đang nhả hạt: vòng xoay quanh icon.
                        if (l.sending || state == DeviceVisualState.moving)
                          Positioned.fill(
                            child: CircularProgressIndicator(
                              strokeWidth: 2.5,
                              color: l.sending ? p.primary : Colors.white,
                            ),
                          ),
                        if (state == DeviceVisualState.offline)
                          const Positioned(right: -4, top: -4, child: _Badge(Icons.cloud_off, offlineColor)),
                        if (state == DeviceVisualState.unknown && !l.sending)
                          Positioned(right: -4, top: -4, child: _Badge(Icons.question_mark, p.textSub)),
                        if (l.feedback == CommandFeedback.error && !l.sending)
                          const Positioned(left: -4, top: -4, child: _Badge(Icons.priority_high, offlineColor)),
                      ],
                    ),
                  ),
                  const SizedBox(height: 3),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: p.card.withValues(alpha: 0.92),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: editing ? p.primary : p.outline),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          device.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          textAlign: TextAlign.center,
                          style: TextStyle(color: p.textMain, fontSize: 10.5, fontWeight: FontWeight.w600),
                        ),
                        Text(
                          l.sending ? 'Đang xử lý...' : view.label,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontSize: 9.5,
                            color: state == DeviceVisualState.offline
                                ? offlineColor
                                : lit
                                    ? accent
                                    : p.textSub,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final IconData icon;
  final Color color;
  const _Badge(this.icon, this.color);

  @override
  Widget build(BuildContext context) => Container(
        width: 18,
        height: 18,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle, border: Border.all(color: context.palette.card, width: 1.5)),
        child: Icon(icon, size: 11, color: Colors.white),
      );
}
