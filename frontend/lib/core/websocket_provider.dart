// frontend/lib/core/websocket_provider.dart

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'realtime_service.dart';

/// Trạng thái huy hiệu "Live" ở tab Trợ lý.
///
/// Trước đây file này tự mở một kết nối /ws riêng (chỉ để echo). Nay cả app
/// dùng MỘT kết nối của [RealtimeService]; đây chỉ là lớp mỏng cho Riverpod —
/// không tạo kết nối thứ hai.
class WebSocketState {
  final bool isConnected;
  const WebSocketState({this.isConnected = false});
}

class WebSocketNotifier extends Notifier<WebSocketState> {
  @override
  WebSocketState build() {
    final rt = RealtimeService.instance;
    void sync() => state = WebSocketState(isConnected: rt.isLive);
    rt.status.addListener(sync);
    ref.onDispose(() => rt.status.removeListener(sync));
    return WebSocketState(isConnected: rt.isLive);
  }

  /// Nối lại ngay (bấm huy hiệu khi đang "Mất kết nối"). Đang nối thì không
  /// tạo thêm kết nối.
  void connect() => RealtimeService.instance.reconnectNow();
}

final webSocketProvider = NotifierProvider<WebSocketNotifier, WebSocketState>(WebSocketNotifier.new);
