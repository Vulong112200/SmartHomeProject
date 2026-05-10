// frontend/lib/core/websocket_provider.dart

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter/foundation.dart';
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

  // Hàm thực hiện kết nối WebSocket
  void connect() {
    if (state.isConnected) return;

    // Kết nối tới Backend FastAPI
    // Nếu chạy Flutter Web trên Chrome:
    // dùng 127.0.0.1 hoặc IP local của máy

    // final wsUrl = Uri.parse('ws://127.0.0.1:8000/ws');
    final wsUrl = Uri.parse('ws://192.168.1.62:8000/ws');

    _channel = WebSocketChannel.connect(wsUrl);

    // Cập nhật trạng thái giao diện:
    // đã kết nối thành công
    state = state.copyWith(isConnected: true);

    // Lắng nghe dữ liệu realtime từ server
    _channel!.stream.listen(
      (message) {
        // Khi server gửi dữ liệu mới
        // thêm vào danh sách message
        state = state.copyWith(
          messages: [...state.messages, message.toString()],
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