// frontend/lib/core/websocket_provider.dart

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter/foundation.dart';

import 'config.dart';
// 1. Định nghĩa trạng thái (Dữ liệu) của WebSocket
class WebSocketState {
  final bool isConnected;
  final List<String> messages;

  WebSocketState({
    this.isConnected = false,
    this.messages = const [],
  });

  // Hàm hỗ trợ sao chép trạng thái cũ và cập nhật dữ liệu mới
  WebSocketState copyWith({
    bool? isConnected,
    List<String>? messages,
  }) {
    return WebSocketState(
      isConnected: isConnected ?? this.isConnected,
      messages: messages ?? this.messages,
    );
  }
}

// 2. Định nghĩa Notifier (Lớp xử lý logic)
class WebSocketNotifier extends Notifier<WebSocketState> {
  WebSocketChannel? _channel;

  @override
  WebSocketState build() {
    // Trạng thái mặc định ban đầu:
    // Chưa kết nối, danh sách tin rỗng
    return WebSocketState();
  }

  bool _connecting = false; // chặn connect trùng khi đang bắt tay

  // Hàm thực hiện kết nối WebSocket
  Future<void> connect() async {
    if (state.isConnected || _connecting) return;
    _connecting = true;

    // Kết nối tới backend trên Render (wss — cùng host với REST API).
    final wsUrl = Uri.parse(AppConfig.wsUrl);

    try {
      final channel = WebSocketChannel.connect(wsUrl);
      // CHỜ bắt tay xong mới báo "Live" — trước đây set isConnected=true ngay
      // sau connect() nên badge hiện Live cả khi server không tồn tại.
      await channel.ready;
      _channel = channel;
      state = state.copyWith(isConnected: true);

      // Lắng nghe dữ liệu realtime từ server
      channel.stream.listen(
        (message) {
          // GIỚI HẠN 200 tin gần nhất — tránh list phình vô hạn theo thời gian.
          final msgs = [...state.messages, message.toString()];
          state = state.copyWith(
            messages: msgs.length > 200 ? msgs.sublist(msgs.length - 200) : msgs,
          );
        },

        // Khi websocket bị đóng
        onDone: () {
          state = state.copyWith(isConnected: false);
        },

        // Khi có lỗi
        onError: (error) {
          state = state.copyWith(isConnected: false);
          debugPrint('Lỗi WebSocket: $error');
        },
      );
    } catch (e) {
      debugPrint('Không kết nối được WebSocket: $e');
      state = state.copyWith(isConnected: false);
    } finally {
      _connecting = false;
    }
  }

  // Gửi dữ liệu lên server
  void sendMessage(String text) {
    if (state.isConnected && _channel != null) {
      _channel!.sink.add(text);
    }
  }

  // Ngắt kết nối websocket
  void disconnect() {
    _channel?.sink.close();

    state = state.copyWith(
      isConnected: false,
      messages: [],
    );
  }
}

// 3. Provider dùng toàn app
final webSocketProvider =
    NotifierProvider<WebSocketNotifier, WebSocketState>(() {
  return WebSocketNotifier();
});